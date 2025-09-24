# app/routers/products.py
from fastapi import APIRouter, Response, Body, HTTPException, Path
from typing import Sequence
import csv, io, asyncio, html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
import aiohttp, httpx

from .realtime import notify_inventory_changed
from .reserves import (
    _fetch_reserved_items, ADMIN_RE, _name_by_tgid,
    _send_tg as _resv_send_tg,
    _msg_reserve_cancel as _msg_reserve_cancel,
    _fetch_items_by_ids as _fetch_items_by_ids,
    _unreserve_and_notify as _unreserve_and_notify,   # используется для снятия + уведомления
)

from ..models import User
from ..security import validate_init_data, extract_tg_id
from ..loaders import (
    PRODUCTS, RESERVED_IDS, searchable_fields, all_categories,
    parts_buckets, map_part_to_bucket, refresh_from_api, refresh_reserves
)
from ..exports import build_prices_xlsx
from ..config import settings
from ..schemas import Product

router = APIRouter(prefix="/api")


def _normalize_sort(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip().lower()
    return s if s in {"price_asc", "price_desc", "brand", "model", "year"} else None


def _sort(items: list[Product], key: str | None):
    k = _normalize_sort(key)
    match k:
        case "price_asc":
            return sorted(items, key=lambda p: (p.price, p.brand, p.model))
        case "price_desc":
            return sorted(items, key=lambda p: (-p.price, p.brand, p.model))
        case "brand":
            return sorted(items, key=lambda p: (p.brand, p.model, p.year))
        case "model":
            return sorted(items, key=lambda p: (p.model, p.brand, p.year))
        case "year":
            return sorted(items, key=lambda p: (p.year, p.brand, p.model))
        case _:
            return items


def _match(p: Product, q: str, fields: Sequence[str] | None):
    if not q:
        return True
    hay = []
    raw = p.__dict__.get("_raw", {})
    if fields:
        for f in fields:
            if f in raw:
                hay.append(str(raw.get(f, "")))
    else:
        hay += [p.brand, p.model, p.part, p.year, raw.get("МАРКИРОВКА ДВИГАТЕЛЯ", ""), raw.get("ВХОДНОЙ АРТИКУЛ", "")]
    ql = q.lower()
    return any(ql in (s or "").lower() for s in hay)


def _short_label(s: str) -> str:
    s = " ".join(s.split())
    if len(s) <= 16:
        return s
    parts = s.split()
    if len(parts) >= 2:
        cand = (parts[0] + " " + parts[1])[:16]
        return cand.rstrip()
    return s[:16].rstrip()


@router.get("/parts")
def parts():
    return {"items": parts_buckets()}


@router.get("/categories")
def categories():
    vals = all_categories()
    items = [{"value": v, "label": _short_label(v), "count": c}
             for v, c in sorted(vals.items(), key=lambda x: (-x[1], x[0]))]
    return {"items": items}


@router.get("/fields")
def fields():
    return {"fields": searchable_fields()}


@router.get("/products")
def products(q: str | None = None, sort: str | None = None,
             fields: str | None = None, cat: str | None = None,
             part: str | None = None, bucket: str | None = None,
             offset: int = 0, limit: int = 20,
             include_reserved: int | None = None):
    scope = [s.strip() for s in (fields or "").split(",") if s and s.strip()]
    offset = max(0, offset)
    limit = max(1, min(200, limit))
    show_reserved = bool(include_reserved)

    def _card(p: Product):
        d = p.model_dump()
        r = p.__dict__.get("_raw", {})
        d["raw"] = {
            "КОРОБКА": r.get("КОРОБКА", ""), "ОБЪЕМ": r.get("ОБЪЕМ", ""),
            "ТИП ДВИГАТЕЛЯ": r.get("ТИП ДВИГАТЕЛЯ", ""), "ТОПЛИВО": r.get("ТОПЛИВО", ""),
            "МАРКИРОВКА ДВИГАТЕЛЯ": r.get("МАРКИРОВКА ДВИГАТЕЛЯ", ""), "ШРОТ": r.get("ШРОТ", ""),
            "ВХОДНОЙ АРТИКУЛ": r.get("ВХОДНОЙ АРТИКУЛ", ""), "Склад": r.get("Склад", ""),
        }
        return d

    def _cat_ok(p: Product):
        if not cat:
            return True
        return (p.__dict__.get("_raw", {}).get("КАТЕГОРИЯ") or "").strip() == cat

    def _bucket_ok(p: Product):
        if not bucket:
            return True
        raw = p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ", "")
        key, _ = map_part_to_bucket(raw)
        return key == bucket

    def _part_ok(p: Product):
        if not part:
            return True
        val = (p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ") or "").strip()
        if val == "Передняя часть (ноускат) в сборе":
            val = "Ноускат"
        return val == part

    items_all = [
        p for p in PRODUCTS
        if _active_only(p)
           and _cat_ok(p) and _bucket_ok(p) and _part_ok(p)
           and _match(p, q or "", scope or None)
    ]

    items_all = _sort(items_all, sort)
    total = len(items_all)
    page = items_all[offset: offset + limit]
    return {"items": [_card(p) for p in page], "total": total, "has_more": (offset + limit) < total}


@router.get("/prices.csv")
def prices_csv(q: str | None = None, sort: str | None = None,
               fields: str | None = None, cat: str | None = None,
               part: str | None = None, bucket: str | None = None):
    scope = [s.strip() for s in (fields or "").split(",") if s and s.strip()]

    def _cat_ok(p: Product):
        if not cat:
            return True
        return (p.__dict__.get("_raw", {}).get("КАТЕГОРИЯ") or "").strip() == cat

    def _bucket_ok(p: Product):
        if not bucket:
            return True
        raw = p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ", "")
        key, _ = map_part_to_bucket(raw)
        return key == bucket

    def _part_ok(p: Product):
        if not part:
            return True
        val = (p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ") or "").strip()
        if val == "Передняя часть (ноускат) в сборе":
            val = "Ноускат"
        return val == part

    filt = [p for p in PRODUCTS
            if _cat_ok(p) and _bucket_ok(p) and _part_ok(p)
            and _match(p, q or "", scope or None)
            and (p.id not in RESERVED_IDS)]
    items = _sort(filt, sort)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "Марка", "Модель", "Год", "Запчасть", "Цена", "Валюта", "Склад"])
    for p in items:
        w.writerow([p.id, p.brand, p.model, p.year, p.part, p.price, p.currency, p.warehouse or ""])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=prices.csv"})


@router.post("/prices.xlsx")
async def prices_xlsx(init_data: str = Body(..., embed=True), q: str | None = None,
                      fields: str | None = None, sort: str | None = None,
                      cat: str | None = None, part: str | None = None, bucket: str | None = None):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(status_code=401, detail="invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(status_code=401, detail="user missing")

    scope = [s.strip() for s in (fields or "").split(",") if s and s.strip()]

    def _cat_ok(p: Product):
        if not cat:
            return True
        return (p.__dict__.get("_raw", {}).get("КАТЕГОРИЯ") or "").strip() == cat

    def _part_ok(p: Product):
        if not part:
            return True
        val = (p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ") or "").strip()
        if val == "Передняя часть (ноускат) в сборе":
            val = "Ноускат"
        return val == part

    def _bucket_ok(p: Product):
        if not bucket:
            return True
        raw = p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ", "")
        key, _ = map_part_to_bucket(raw)
        return key == bucket

    filt = [p for p in PRODUCTS
            if _cat_ok(p) and _bucket_ok(p) and _part_ok(p)
            and _match(p, q or "", scope or None)
            and (p.id not in RESERVED_IDS)]
    items = _sort(filt, sort)

    buf = build_prices_xlsx(items)
    bot = Bot(settings.bot_token)
    try:
        from aiogram.types import BufferedInputFile
        await bot.send_document(chat_id=int(tg_id),
                                document=BufferedInputFile(buf.getvalue(), filename="prices.xlsx"),
                                caption="Прайс-лист")
    finally:
        await bot.session.close()
    return {"ok": True}


@router.post("/prices_split.xlsx")
async def prices_split(init_data: str = Body(..., embed=True),
                       q: str | None = None,
                       fields: str | None = None,
                       sort: str | None = None,
                       cat: str | None = None,
                       bucket: str | None = None,
                       part: str | None = None):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(status_code=401, detail="invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(status_code=401, detail="user missing")

    scope = [s.strip() for s in (fields or "").split(",") if s and s.strip()]

    def _cat_ok(p: Product):
        if not cat:
            return True
        return (p.__dict__.get("_raw", {}).get("КАТЕГОРИЯ") or "").strip() == cat

    def _bucket_ok(p: Product):
        if not bucket:
            return True
        raw = p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ", "")
        key, _ = map_part_to_bucket(raw)
        return key == bucket

    def _part_ok(p: Product):
        if not part:
            return True
        return (p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ") or "").strip() == part

    pool = [p for p in PRODUCTS
            if _cat_ok(p) and _bucket_ok(p) and _part_ok(p)
            and _match(p, q or "", scope or None)
            and (p.id not in RESERVED_IDS)]
    ENGINES_RAW = "Двигатель"
    NOSECUT_RAW = "Передняя часть (ноускат) в сборе"

    engines, nosecuts, others = [], [], []
    for p in pool:
        raw_part = (p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ") or "").strip()
        if raw_part == ENGINES_RAW:
            engines.append(p)
        elif raw_part == NOSECUT_RAW:
            nosecuts.append(p)
        else:
            others.append(p)

    engines = _sort(engines, sort)
    nosecuts = _sort(nosecuts, sort)
    others = sorted(others, key=lambda p: (p.part, p.brand))

    bot = Bot(settings.bot_token)
    from aiogram.types import BufferedInputFile
    try:
        if engines:
            buf = build_prices_xlsx(engines)
            await bot.send_document(int(tg_id), BufferedInputFile(buf.getvalue(), "Двигатели.xlsx"))
        if nosecuts:
            buf = build_prices_xlsx(nosecuts)
            await bot.send_document(int(tg_id), BufferedInputFile(buf.getvalue(), "Ноускаты.xlsx"))
        if others:
            buf = build_prices_xlsx(others)
            await bot.send_document(int(tg_id), BufferedInputFile(buf.getvalue(), "Прочие запчасти.xlsx"))
    finally:
        await bot.session.close()

    return {"ok": True}


def _get_product(pid: int) -> Product | None:
    for p in PRODUCTS:
        if p.id == pid:
            return p
    return None


def _active_only(p: Product) -> bool:
    return str(p.__dict__.get("_stock_status", "0")) == "0" and str(p.__dict__.get("_deleted", "0")) == "0"


@router.get("/product/{pid}")
def product_one(pid: int = Path(...)):
    p = _get_product(pid)
    if not p:
        raise HTTPException(status_code=404, detail="not found")
    d = p.model_dump()
    r = p.__dict__.get("_raw", {})
    vids = []
    vraw = (r.get("ВИДЕО") or "").strip()
    if vraw:
        vids = [x.strip() for x in vraw.split(",") if x.strip()]
    d["raw"] = {
        "ШРОТ": r.get("ШРОТ", ""), "ВХОДНОЙ АРТИКУЛ": r.get("ВХОДНОЙ АРТИКУЛ", ""),
        "ТОПЛИВО": r.get("ТОПЛИВО", ""), "ОБЪЕМ": r.get("ОБЪЕМ", ""),
        "ТИП ДВИГАТЕЛЯ": r.get("ТИП ДВИГАТЕЛЯ", ""), "КОРОБКА": r.get("КОРОБКА", ""),
        "ТИП КУЗОВА": r.get("ТИП КУЗОВА", ""), "ОРИГИНАЛЬНЫЙ НОМЕР": r.get("ОРИГИНАЛЬНЫЙ НОМЕР", ""),
        "ПРИВОД": r.get("ПРИВОД", ""), "Склад": r.get("Склад", ""),
        "VIN": r.get("VIN", ""), "VRN": r.get("VRN", ""),
    }
    d["videos"] = vids
    return d


# ---- анти-даблклик для резерва ----
_reserve_locks: dict[int, asyncio.Lock] = {}


def _get_lock(zap: int) -> asyncio.Lock:
    if zap not in _reserve_locks:
        _reserve_locks[zap] = asyncio.Lock()
    return _reserve_locks[zap]


@router.post("/reserve")
async def set_reserve(
        init_data: str = Body(..., embed=True),
        zap: int = Body(..., embed=True),
        comment: str = Body("", embed=True),
        till: str | None = Body(None, embed=True),
):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(status_code=401, detail="invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(status_code=401, detail="user missing")

    # проверка админа + имя из БД
    is_admin = False
    admin_name = ""
    admin_tag = f"id:{tg_id}"
    try:
        from sqlalchemy.orm import Session
        from ..db import SessionLocal
        with SessionLocal() as s:  # type: ignore
            u = s.query(User).filter(User.tg_id == tg_id).first()
            is_admin = bool(u and u.is_admin) or (str(tg_id) == str(settings.admin_id))
            if u:
                admin_name = (u.name or "").strip()
                admin_tag = (f"{admin_name} ({u.tg_id})").strip()
    except Exception:
        is_admin = (str(tg_id) == str(settings.admin_id))
    if not is_admin:
        raise HTTPException(status_code=403, detail="forbidden")

    # МСК +4 дня (дата без времени)
    msk = ZoneInfo("Europe/Moscow")
    reserve_date = (datetime.now(msk).date() + timedelta(days=4)).isoformat()

    p = _get_product(zap)
    if not p:
        raise HTTPException(status_code=404, detail="product not found")

    lock = _get_lock(zap)
    async with lock:
        payload_comment = f"[admin: {admin_name or f'id:{tg_id}'} ({tg_id})] {(comment or '').strip()}".strip()

        url = f"{settings.inventory_api}?action=change_status"
        body = {
            "user_id": settings.inventory_user_id,
            "item_ids": [zap],
            "status": 2,
            "options": {"reserve_date": reserve_date, "comment": payload_comment}
        }
        headers = {"Content-Type": "application/json"}
        if settings.inventory_auth:
            headers["Authorization"] = settings.inventory_auth
        try:
            async with httpx.AsyncClient(timeout=25) as cli:
                resp = await cli.put(url, json=body, headers=headers)
                if resp.status_code >= 400:
                    raise HTTPException(status_code=503, detail="no connection to inventory")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=503, detail="no connection to inventory")

        # форс‑обновления и live‑нотификация
        try:
            await refresh_from_api(force=True)
        except Exception as e:
            print("reserve force refresh error:", e)
        try:
            changed = await refresh_reserves(force=True)
            if changed:
                try:
                    notify_inventory_changed()
                except Exception:
                    pass
        except Exception as e:
            print("refresh_reserves after reserve error:", e)

        # уведомление в группу
        try:
            bot = Bot(settings.bot_token)
            r = p.__dict__.get("_raw", {})
            lines = []

            def add(label, value):
                v = (value or "").strip()
                if v:
                    lines.append(f"<b>{html.escape(label)}:</b> {html.escape(v)}")

            title = f"{p.brand} {p.model}".strip()
            header = f"🟡 <b>Резерв</b> — {html.escape(title)}"
            add("Запчасть", p.part)
            add("Год", p.year)
            add("Топливо", r.get("ТОПЛИВО", ""))
            vol = (r.get("ОБЪЕМ", "") or "").strip()
            et = (r.get("ТИП ДВИГАТЕЛЯ", "") or "").strip()
            if vol or et:
                add("Двигатель", f"{vol}{(' ' if vol and et else '')}{et}")
            add("Маркировка дв.", r.get("МАРКИРОВКА ДВИГАТЕЛЯ", ""))
            add("Коробка", r.get("КОРОБКА", ""))
            add("Кузов", r.get("ТИП КУЗОВА", ""))
            if p.price or p.currency:
                add("Цена", f"{p.price or ''} {p.currency or ''}")
            add("На складе", r.get("Склад", ""))
            razb = " ".join(x for x in [(r.get("ШРОТ") or "").strip(), (r.get("ВХОДНОЙ АРТИКУЛ") or "").strip()] if x)
            if razb:
                add("Разборочный", razb)
            # Описание (из Product.description или RAW)
            add("Описание", (p.description or r.get("ОПИСАНИЕ", "")))
            add("VIN", r.get("VIN", ""))
            add("VRN", r.get("VRN", ""))
            add("Резерв до", reserve_date)
            add("Админ", admin_name or f"id:{tg_id}")
            if comment:
                add("Комментарий", comment)

            text = header + "\n" + "\n".join(lines)
            kwargs = {"chat_id": int(settings.notify_chat_id_reserve)}
            if getattr(settings, "notify_thread_id_reserve", 0):
                kwargs["message_thread_id"] = int(settings.notify_thread_id_reserve)
            await bot.send_message(**kwargs, text=text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            print("reserve notify error:", e)
        finally:
            try:
                await bot.session.close()
            except:
                pass

        return {"ok": True, "till": reserve_date}


@router.post("/product/{pid}/send_photos")
async def product_send_photos(pid: int = Path(...), init_data: str = Body(..., embed=True)):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(status_code=401, detail="invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(status_code=401, detail="user missing")

    p = _get_product(pid)
    if not p or not p.photos:
        raise HTTPException(status_code=400, detail="no photos")

    r = p.__dict__.get("_raw", {})
    caption = " ".join(filter(None, [
        f"{p.brand} {p.model}".strip(),
        f"• {p.part}".strip() if p.part else "",
        f"• {(r.get('ШРОТ') or '').strip()} {(r.get('ВХОДНОЙ АРТИКУЛ') or '').strip()}".strip()
        if (r.get('ШРОТ') or r.get('ВХОДНОЙ АРТИКУЛ')) else "",
        f"• {r.get('Склад', '').strip()}" if r.get('Склад') else ""
    ]))

    urls = []
    for u in p.photos:
        if not u:
            continue
        u = u.strip()
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("http://"):
            u = "https://" + u[7:]
        if not u.startswith("http"):
            continue
        urls.append(u)
    urls = urls[:20]

    bot = Bot(settings.bot_token)

    async def send_group(url_batch: list[str]) -> bool:
        from aiogram.types import InputMediaPhoto
        media = [InputMediaPhoto(media=u) for u in url_batch]
        if media:
            media[0].caption = caption
        try:
            await bot.send_media_group(chat_id=int(tg_id), media=media)
            return True
        except TelegramBadRequest as e:
            print("send_media_group failed:", e)
            return False
        except Exception as e:
            print("send_media_group error:", e)
            return False

    async def download_bytes(url: str, timeout=15) -> bytes | None:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=timeout) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception as e:
            print("download failed:", url, e)
        return None

    async def send_single(url: str, with_caption: bool) -> None:
        try:
            await bot.send_photo(chat_id=int(tg_id), photo=url, caption=caption if with_caption else None)
            return
        except Exception as e:
            print("send_photo URL error:", e)
        data = await download_bytes(url)
        if not data:
            return
        from aiogram.types import BufferedInputFile
        import os
        from urllib.parse import urlparse
        name = os.path.basename(urlparse(url).path) or "photo.jpg"
        try:
            await bot.send_photo(chat_id=int(tg_id),
                                 photo=BufferedInputFile(data, filename=name),
                                 caption=caption if with_caption else None)
        except Exception as e:
            print("send_photo file error:", e)

    try:
        batches = [urls[i:i + 10] for i in range(0, len(urls), 10)]
        all_ok = True
        for i, batch in enumerate(batches):
            ok_batch = await send_group(batch)
            if not ok_batch:
                all_ok = False
                for j, u in enumerate(batch):
                    await send_single(u, with_caption=(i == 0 and j == 0))
        return {"ok": True, "mode": "media_group" if all_ok else "fallback_single"}
    finally:
        await bot.session.close()


@router.post("/reserve/remove")
async def remove_reserve(
    init_data: str = Body(..., embed=True),
    zap: int = Body(..., embed=True),
    reason: str = Body("", embed=True),
):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(status_code=401, detail="invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(status_code=401, detail="user missing")

    # единый метод + указываем, кто снял
    await _unreserve_and_notify(int(zap), reason or "", actor_tg=tg_id)

    # обновление кешей
    try:
        await refresh_from_api(force=True)
        if await refresh_reserves(force=True):
            notify_inventory_changed()
    except Exception:
        pass

    return {"ok": True}







@router.post("/refresh")
async def force_refresh():
    await refresh_from_api(force=True)
    # сразу обновим кеш резервов и, если изменилось, дёрнем live‑обновление
    try:
        changed = await refresh_reserves(force=True)
        if changed:
            try:
                notify_inventory_changed()
            except Exception:
                pass
    except Exception as e:
        print("force_refresh: refresh_reserves failed:", e)
    return {"ok": True}


@router.post("/unreserve")
async def unset_reserve(
        init_data: str = Body(..., embed=True),
        zap: int = Body(..., embed=True),
):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(status_code=401, detail="invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(status_code=401, detail="user missing")

    # тот же чек админа, что и выше
    is_admin = False
    try:
        from sqlalchemy.orm import Session
        from ..db import SessionLocal
        with SessionLocal() as s:  # type: ignore
            u = s.query(User).filter(User.tg_id == tg_id).first()
            is_admin = bool(u and u.is_admin) or (str(tg_id) == str(settings.admin_id))
    except Exception:
        is_admin = (str(tg_id) == str(settings.admin_id))
    if not is_admin:
        raise HTTPException(status_code=403, detail="forbidden")

    url = f"{settings.inventory_api}?action=change_status"
    payload = {
        "user_id": settings.inventory_user_id,
        "item_ids": [int(zap)],
        "status": 0,  # вернуть на склад
        "options": {}
    }
    headers = {"Content-Type": "application/json"}
    if settings.inventory_auth:
        headers["Authorization"] = settings.inventory_auth

    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            resp = await cli.put(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise HTTPException(status_code=503, detail="no connection to inventory")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="no connection to inventory")

    # обновляем данные/резервы и дергаем SSE
    try:
        await refresh_from_api(force=True)
    except Exception as e:
        print("unreserve force refresh error:", e)
    try:
        changed = await refresh_reserves(force=True)
        if changed:
            try:
                notify_inventory_changed()
            except Exception:
                pass
    except Exception as e:
        print("refresh_reserves after unreserve error:", e)

    return {"ok": True}


@router.get("/reserves")
def reserves(q: str | None = None,
             sort: str | None = None,
             bucket: str | None = None,
             offset: int = 0, limit: int = 20):
    # те же вспомогательные, что в /products
    def _card(p: Product):
        d = p.model_dump()
        r = p.__dict__.get("_raw", {})
        d["raw"] = {
            "КОРОБКА": r.get("КОРОБКА", ""), "ОБЪЕМ": r.get("ОБЪЕМ", ""),
            "ТИП ДВИГАТЕЛЯ": r.get("ТИП ДВИГАТЕЛЯ", ""), "ТОПЛИВО": r.get("ТОПЛИВО", ""),
            "МАРКИРОВКА ДВИГАТЕЛЯ": r.get("МАРКИРОВКА ДВИГАТЕЛЯ", ""), "ШРОТ": r.get("ШРОТ", ""),
            "ВХОДНОЙ АРТИКУЛ": r.get("ВХОДНОЙ АРТИКУЛ", ""), "Склад": r.get("Склад", ""),
        }
        return d

    def _bucket_ok(p: Product):
        if not bucket:
            return True
        raw = p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ", "")
        key, _ = map_part_to_bucket(raw)
        return key == bucket

    scope = None  # поиск по умолчанию по основным полям
    pool = [p for p in PRODUCTS
            if (p.id in RESERVED_IDS) and _bucket_ok(p) and _match(p, q or "", scope)]
    pool = _sort(pool, sort)

    total = len(pool)
    page = pool[max(0, offset): max(0, offset) + max(1, min(200, limit))]
    return {"items": [_card(p) for p in page], "total": total, "has_more": (offset + limit) < total}


@router.post("/reserves/refresh")
async def reserves_force_refresh():
    changed = await refresh_reserves(force=True)
    return {"ok": True, "changed": bool(changed)}


@router.patch("/reserves/{item_id}/comment")
async def reserves_comment_edit(
        item_id: int = Path(...),
        init_data: str = Body(..., embed=True),
        comment: str = Body("", embed=True),
):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(status_code=401, detail="invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(status_code=401, detail="user missing")

    # — имя редактора из БД
    editor_name = _name_by_tgid(tg_id) or "Неизвестный"
    try:
        from ..db import SessionLocal
        with SessionLocal() as s:  # type: ignore
            u = s.query(User).filter(User.tg_id == tg_id).first()
            editor_name = (u.name or "").strip() if u else editor_name
    except Exception:
        pass

    # — текущий item (для старого комментария и даты резерва)
    cur = None
    try:
        items = await _fetch_reserved_items()
        cur = next((it for it in items if str(it.get("id")) == str(item_id)), None)
    except Exception:
        cur = None

    old_full = (cur.get("comment") or "") if cur else ""
    old_user = ADMIN_RE.sub("", old_full, count=1).strip()
    reserve_date = (cur.get("reserve_date") or "").split(" ")[0] if cur else ""
    if not reserve_date:
        msk = ZoneInfo("Europe/Moscow")
        reserve_date = (datetime.now(msk).date() + timedelta(days=4)).isoformat()

    # — новый полный комментарий с админ‑префиксом
    admin_prefix = f"[admin: {editor_name or f'id:{tg_id}'} ({tg_id})]"
    new_user = (comment or "").strip()
    new_full = f"{admin_prefix} {new_user}".strip()

    # — API: статус=2 (резерв), с прежней датой
    url = f"{settings.inventory_api}?action=change_status"
    payload = {
        "user_id": settings.inventory_user_id,
        "item_ids": [int(item_id)],
        "status": 2,
        "options": {"reserve_date": reserve_date, "comment": new_full},
    }
    headers = {"Content-Type": "application/json"}
    if settings.inventory_auth:
        headers["Authorization"] = settings.inventory_auth

    try:
        async with httpx.AsyncClient(timeout=25) as cli:
            r = await cli.put(url, json=payload, headers=headers)
            if r.status_code >= 400:
                raise HTTPException(status_code=503, detail="no connection to inventory")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="no connection to inventory")

    # — рефреш и нотификация каталога
    try:
        await refresh_from_api(force=True)
    except Exception:
        pass
    try:
        changed = await refresh_reserves(force=True)
        if changed:
            try:
                notify_inventory_changed()
            except Exception:
                pass
    except Exception:
        pass

    # — TG уведомление
    try:
        bot = Bot(settings.bot_token)
        p = next((p for p in PRODUCTS if int(p.id) == int(item_id)), None)

        lines = []

        def add(lbl, val):
            v = (val or "").strip()
            if v:
                lines.append(f"<b>{html.escape(lbl)}:</b> {html.escape(v)}")

        header = "✏️ <b>Изменение комментария резерва</b>"
        if p:
            r = p.__dict__.get("_raw", {})
            title = f"{p.brand} {p.model}".strip()
            header += f" — {html.escape(title)}"
            add("Запчасть", p.part)
            add("Год", p.year)
            add("Топливо", r.get("ТОПЛИВО", ""))
            vol = (r.get("ОБЪЕМ", "") or "").strip()
            et = (r.get("ТИП ДВИГАТЕЛЯ", "") or "").strip()
            if vol or et:
                add("Двигатель", f"{vol}{(' ' if vol and et else '')}{et}")
            add("Маркировка дв.", r.get("МАРКИРОВКА ДВИГАТЕЛЯ", ""))
            add("Коробка", r.get("КОРОБКА", ""))
            add("Кузов", r.get("ТИП КУЗОВА", ""))
            if p.price or p.currency:
                add("Цена", f"{p.price or ''} {p.currency or ''}")
            add("На складе", r.get("Склад", ""))
            razb = " ".join(x for x in [(r.get("ШРОТ") or "").strip(), (r.get("ВХОДНОЙ АРТИКУЛ") or "").strip()] if x)
            if razb:
                add("Разборочный", razb)
            # Описание
            add("Описание", (p.description or r.get("ОПИСАНИЕ", "")))

        lines.append(f"<b>До:</b> “{html.escape(old_user)}”")
        lines.append(f"<b>После:</b> “{html.escape(new_user)}”")
        lines.append(f"<b>Редактировал:</b> {html.escape(editor_name or f'id:{tg_id}')}")

        text = header + "\n" + "\n".join(lines)
        kwargs = {"chat_id": int(settings.notify_chat_id_reserve)}
        if getattr(settings, "notify_thread_id_reserve", 0):
            kwargs["message_thread_id"] = int(settings.notify_thread_id_reserve)
        await bot.send_message(**kwargs, text=text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        print("reserve comment notify error:", e)
    finally:
        try:
            await bot.session.close()
        except:
            pass

    return {"ok": True}
