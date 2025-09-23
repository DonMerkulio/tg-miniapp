from __future__ import annotations
import re, html
from datetime import datetime, timedelta, timezone
import httpx
from fastapi import APIRouter, Query, Body, HTTPException
from aiogram import Bot

from ..config import settings
from .realtime import notify_inventory_changed
from ..db import SessionLocal
from ..models import User
from ..security import validate_init_data, extract_tg_id
from ..loaders import PRODUCTS  # ← fallback-источник, если админ-API не отдаст карточку

router = APIRouter(prefix="/api", tags=["reserves"])

LIST_URL = f"{settings.api_base}/api/items.php?action=list&limit=10000&with_photo=1&filters[stock_status]=2"
ADMIN_RE = re.compile(r"^\s*\[admin:\s*([^\(]+?)\s*\((\d+)\)\]\s*", re.IGNORECASE)
MSK = timezone(timedelta(hours=3))


def _name_by_tgid(tg: str | int) -> str | None:
    try:
        with SessionLocal() as s:  # type: ignore
            u = s.query(User).filter(User.tg_id == str(tg)).first()
            n = (u.name or "").strip() if u else ""
            return n or None
    except Exception:
        return None


def _msk_plus_days_ymd(days: int = 4) -> str:
    return (datetime.now(MSK) + timedelta(days=days)).strftime("%Y-%m-%d")


def _strip_admin_prefix(comment: str) -> str:
    return ADMIN_RE.sub("", (comment or "").strip()).strip()


def _with_admin_prefix(comment: str, admin_tag: str | None) -> str:
    body = _strip_admin_prefix(comment)
    tag = (admin_tag or "").strip()
    return f"{tag} {body}".strip() if tag else body


async def _change_status(item_ids: list[int], status: int, options: dict | None = None) -> dict:
    url = f"{settings.api_base}/api/items.php?action=change_status"
    payload = {
        "user_id": settings.api_user_id,
        "item_ids": [int(x) for x in item_ids],
        "status": int(status),
        "options": options or {}
    }
    async with httpx.AsyncClient(timeout=25) as cli:
        r = await cli.put(url, json=payload)
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"inventory: {r.text}")
        return r.json()


async def _fetch_reserved_items() -> list[dict]:
    async with httpx.AsyncClient(timeout=25) as cli:
        r = await cli.get(LIST_URL)
        r.raise_for_status()
        j = r.json()
        return (j or {}).get("data", {}).get("items", []) if isinstance(j, dict) else []


def _extract_articles(item: dict) -> tuple[str, str, str]:
    """
    Возвращает (shrot_letter, input_article, 'LETTER NNN').
    Если полей нет — пытается вытащить из title (… ##<склад> <буква> <номер>).
    """
    f = item.get("fields") or {}
    sh = ((f.get("shrot_id") or {}).get("display_value") or "").strip()
    ia = ((f.get("input_article") or {}).get("value") or "").strip()
    if not sh or not ia:
        title = (item.get("title") or "").strip()
        m = re.search(r"##\S+\s+([A-Za-zА-Яа-я])\s+(\d+)", title)
        if m:
            if not sh:
                sh = m.group(1).upper()
            if not ia:
                ia = m.group(2)
    art = " ".join(x for x in [sh, ia] if x).strip()
    return sh, ia, art


# УСТОЙЧИВАЯ загрузка карточек по id
async def _fetch_items_by_ids(ids: list[int]) -> list[dict]:
    base = f"{settings.api_base}/api/items.php"

    def only_requested(items: list[dict]) -> list[dict]:
        want = {int(x) for x in ids}
        out = []
        for it in items or []:
            try:
                i = int(it.get("id", 0))
            except Exception:
                continue
            if i in want:
                out.append(it)
        return out

    # 1) ids[]
    try:
        params = [("action", "list"), ("with_photo", "0")]
        for i in ids:
            params.append(("ids[]", str(int(i))))
        async with httpx.AsyncClient(timeout=25) as cli:
            r = await cli.get(base, params=params)
            r.raise_for_status()
            j = r.json()
            items = (j or {}).get("data", {}).get("items", []) if isinstance(j, dict) else []
        sel = only_requested(items)
        if len(sel) == len(ids):
            return sel
    except Exception:
        pass

    # 2) filters[id] для одиночного случая
    if len(ids) == 1:
        try:
            params = [("action", "list"), ("with_photo", "0"), ("filters[id]", str(int(ids[0])))]
            async with httpx.AsyncClient(timeout=25) as cli:
                r = await cli.get(base, params=params)
                r.raise_for_status()
                j = r.json()
                items = (j or {}).get("data", {}).get("items", []) if isinstance(j, dict) else []
            sel = only_requested(items)
            if sel:
                return sel
        except Exception:
            pass

    # 3) по одному запросу на id
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=25) as cli:
        for i in ids:
            try:
                params = [("action", "list"), ("with_photo", "0"), ("filters[id]", str(int(i)))]
                r = await cli.get(base, params=params)
                r.raise_for_status()
                j = r.json()
                items = (j or {}).get("data", {}).get("items", []) if isinstance(j, dict) else []
                sel = only_requested(items)
                if sel:
                    out.extend(sel)
            except Exception:
                continue
    return out


def _fields(item: dict) -> dict:
    f = item.get("fields") or {}
    g = lambda key, sub="display_value": ((f.get(key) or {}) or {}).get(sub) or ""
    v = lambda key: ((f.get(key) or {}) or {}).get("value") or ""

    brand = g("car_brand_id")
    model = g("car_model_id")
    part = g("part_id")
    year = str(v("year")).strip()

    capacity = g("capacity_id")          # 2.0 / 1.9 …
    fuel = g("type_id")                  # бензин / дизель
    engine_mark = v("mark_engine")       # N47D20A и т.п.
    gearbox = g("kpp_id")                # МКПП/АКПП
    body = g("body_id")                  # Седан/Хэтчбек…
    warehouse = g("stock_id")

    # разборочный «Буква Номер»
    _, _, articles = _extract_articles(item)

    price = str(item.get("price_dollar") or "").strip()
    currency = "USD" if price else ""
    vin = v("vin_number")
    vrn = v("vrn_number")
    description = v("description")

    return {
        "brand": brand, "model": model, "part": part, "year": year,
        "capacity": capacity, "fuel": fuel, "engine_mark": engine_mark,
        "gearbox": gearbox, "body": body, "warehouse": warehouse,
        "articles": articles, "price": price, "currency": currency,
        "vin": vin, "vrn": vrn, "description": description,
    }


def _msg_reserve_set(item: dict, reserve_date: str, admin_tag: str | None, comment: str) -> str:
    f = _fields(item)
    title = f"{(f.get('brand') or '').strip()} {(f.get('model') or '').strip()}".strip()
    lines = []
    def add(lbl, val):
        v = (val or "").strip()
        if v: lines.append(f"<b>{html.escape(lbl)}:</b> {html.escape(v)}")

    add("Запчасть", f.get("part"))
    add("Год", f.get("year"))
    cap, fu = f.get("capacity",""), f.get("fuel","")
    if cap or fu: add("Двигатель", f"{cap}{(' ' if cap and fu else '')}{fu}")
    add("Маркировка дв.", f.get("engine_mark"))
    add("Коробка", f.get("gearbox"))
    add("Кузов", f.get("body"))
    if f.get("price"): add("Цена", f"{f.get('price')} {f.get('currency','')}".strip())
    add("На складе", f.get("warehouse"))
    add("Разборочный", f.get("articles"))
    add("Описание", f.get("description"))
    add("VIN", f.get("vin")); add("VRN", f.get("vrn"))
    add("Резерв до", reserve_date)
    if admin_tag: add("Админ", _strip_admin_prefix(admin_tag))
    if comment: add("Комментарий", _strip_admin_prefix(comment))
    return f"🟡 <b>Резерв</b> — {html.escape(title)}\n" + "\n".join(lines)


def _msg_reserve_cancel(item: dict, admin_tag: str | None, reason: str | None) -> str:
    f = _fields(item)
    title = f"{(f.get('brand') or '').strip()} {(f.get('model') or '').strip()}".strip()
    lines = []
    def add(lbl, val):
        v = (val or "").strip()
        if v: lines.append(f"<b>{html.escape(lbl)}:</b> {html.escape(v)}")

    add("Запчасть", f.get("part"))
    add("Год", f.get("year"))
    cap, fu = f.get("capacity",""), f.get("fuel","")
    if cap or fu: add("Двигатель", f"{cap}{(' ' if cap and fu else '')}{fu}")
    add("Маркировка дв.", f.get("engine_mark"))
    add("Коробка", f.get("gearbox"))
    add("Кузов", f.get("body"))
    if f.get("price"): add("Цена", f"{f.get('price')} {f.get('currency','')}".strip())
    add("На складе", f.get("warehouse"))
    add("Разборочный", f.get("articles"))
    add("Описание", f.get("description"))
    add("VIN", f.get("vin")); add("VRN", f.get("vrn"))
    if admin_tag: add("Админ", _strip_admin_prefix(admin_tag))
    if reason: add("Причина", reason)
    return f"🔴 <b>Снят резерв</b> — {html.escape(title)}\n" + "\n".join(lines)


# --- fallback: формирование сообщения из витринного Product ---
def _msg_reserve_cancel_from_product(p, reason: str | None, admin_name: str | None = None) -> str:
    r = p.__dict__.get("_raw", {})
    title = f"{(p.brand or '').strip()} {(p.model or '').strip()}".strip()
    lines = []

    def add(lbl, val):
        v = (val or "").strip()
        if v:
            lines.append(f"<b>{html.escape(lbl)}:</b> {html.escape(v)}")

    add("Запчасть", p.part)
    add("Год", p.year)
    fuel = r.get("ТОПЛИВО", "")
    vol = (r.get("ОБЪЕМ", "") or "").strip()
    et  = (r.get("ТИП ДВИГАТЕЛЯ", "") or "").strip()
    if vol or et: add("Двигатель", f"{vol}{(' ' if vol and et else '')}{et or fuel}")
    add("Маркировка дв.", r.get("МАРКИРОВКА ДВИГАТЕЛЯ", ""))
    add("Коробка", r.get("КОРОБКА", ""))
    add("Кузов", r.get("ТИП КУЗОВА", ""))
    if p.price or p.currency: add("Цена", f"{p.price or ''} {p.currency or ''}".strip())
    add("На складе", r.get("Склад", ""))
    art = " ".join(x for x in [(r.get("ШРОТ") or "").strip(), (r.get("ВХОДНОЙ АРТИКУЛ") or "").strip()] if x)
    add("Разборочный", art)
    add("Описание", r.get("ОПИСАНИЕ", ""))
    add("VIN", r.get("VIN", "")); add("VRN", r.get("VRN", ""))
    if admin_name: add("Админ", admin_name)
    if reason: add("Причина", reason)
    return f"🔴 <b>Снят резерв</b> — {html.escape(title)}\n" + "\n".join(lines)


async def _send_tg(text: str) -> None:
    bot = Bot(settings.bot_token)
    try:
        kwargs = {
            "chat_id": int(settings.notify_chat_id_reserve),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        tid = getattr(settings, "notify_thread_id_reserve", 0)
        if tid and int(tid) > 0:
            kwargs["message_thread_id"] = int(tid)
        await bot.send_message(**kwargs)
    except Exception as e:
        print("reserve notify error:", e, flush=True)
    finally:
        await bot.session.close()


async def _unreserve_and_notify(
    item_id: int,
    reason: str | None = "",
    actor_tg: str | int | None = None,   # ← кто снял
) -> None:
    # имя того, кто снял резерв
    admin_name = None
    try:
        if actor_tg is not None:
            admin_name = _name_by_tgid(actor_tg) or f"id:{actor_tg}"
    except Exception:
        admin_name = f"id:{actor_tg}" if actor_tg is not None else None

    # карточку берём ДО смены статуса
    items = await _fetch_items_by_ids([int(item_id)])

    # снять резерв
    await _change_status([int(item_id)], status=0, options={})

    # уведомление
    if items:
        await _send_tg(_msg_reserve_cancel(items[0], admin_tag=admin_name, reason=reason or ""))
    else:
        txt = f"🔴 <b>Снят резерв</b> — ID {int(item_id)}"
        if (reason or "").strip():
            txt += f"\n<b>Причина:</b> {html.escape(reason)}"
        if admin_name:
            txt += f"\n<b>Админ:</b> {html.escape(admin_name)}"
        await _send_tg(txt)

    notify_inventory_changed()



def _photo_urls(item: dict) -> list[str]:
    out = []
    for ph in item.get("photos") or []:
        u = (ph.get("url") or "").strip()
        if not u:
            continue
        if u.startswith("/"):
            u = settings.api_base + u
        out.append(u)
    return out


def _card(item: dict) -> dict:
    f = item.get("fields") or {}

    brand = (f.get("car_brand_id", {}).get("display_value") or "").strip()
    model = (f.get("car_model_id", {}).get("display_value") or "").strip()
    part = (f.get("part_id", {}).get("display_value") or "").strip()
    year = str((f.get("year", {}).get("value") or "")).strip()

    _, _, articles = _extract_articles(item)

    engine_mark = (f.get("mark_engine", {}).get("value") or "").strip()
    warehouse = (f.get("stock_id", {}).get("display_value") or "").strip()

    comment_raw = (item.get("comment") or "").strip()
    admin_name = admin_tg = ""
    user_comment = comment_raw
    m = ADMIN_RE.match(comment_raw)
    if m:
        admin_name = m.group(1).strip()
        admin_tg = m.group(2).strip()
        user_comment = comment_raw[m.end():].strip()
    if admin_tg:
        real = _name_by_tgid(admin_tg)
        if real:
            admin_name = real

    till = (item.get("reserve_date") or "").strip()

    return {
        "id": int(item.get("id")),
        "brand": brand,
        "model": model,
        "part": part,
        "year": year,
        "articles": articles,
        "engine_mark": engine_mark,
        "warehouse": warehouse,
        "photos": _photo_urls(item),
        "reserve_till": till,
        "comment": user_comment,
        "user_comment": user_comment,
        "admin_name": admin_name,
        "admin_tg_id": admin_tg,
        "admin_tag": f"[admin: {admin_name} ({admin_tg})]" if admin_tg else "",
    }


@router.get("/reserves/admins")
async def reserves_admins():
    items = await _fetch_reserved_items()
    groups: dict[str, dict] = {}
    unknown = 0
    for it in items:
        c = _card(it)
        if c["admin_tg_id"]:
            shown_name = c["admin_name"] or _name_by_tgid(c["admin_tg_id"]) or f"id:{c['admin_tg_id']}"
            g = groups.setdefault(c["admin_tg_id"], {"tg_id": c["admin_tg_id"], "name": shown_name, "count": 0})
            g["name"] = shown_name
            g["count"] += 1
        else:
            unknown += 1
    admins = sorted(groups.values(), key=lambda x: (-x["count"], x["name"]))
    return {"admins": admins, "unknown": unknown}


@router.get("/reserves/list")
async def reserves_list(admin: str | None = Query(None, description="tg_id администратора; '_' — без тега")):
    items = await _fetch_reserved_items()
    out = []
    for it in items:
        c = _card(it)
        if admin is None:
            out.append(c)
        elif admin == "_" and not c["admin_tg_id"]:
            out.append(c)
        elif c["admin_tg_id"] == str(admin):
            out.append(c)
    out.sort(key=lambda x: (x["brand"], x["model"], x["part"], x["id"]))
    return {"items": out}


@router.get("/reserves")
async def reserves_list_compat(admin: str | None = None,
                               unknown: int | None = None,
                               tag: str | None = None):
    if unknown:
        admin = "_"
    if tag and not admin:
        m = ADMIN_RE.search(tag)
        if m:
            admin = m.group(2)  # tg_id
    return await reserves_list(admin=admin)


@router.patch("/reserves/{item_id}/comment")
async def reserves_update_comment(item_id: int, data: dict = Body(...)):
    admin_tag = data.get("admin_tag") or ""
    comment_body = data.get("comment") or ""
    reserve_date = (data.get("reserve_date") or _msk_plus_days_ymd())
    await _change_status([item_id], status=2, options={
        "reserve_date": reserve_date,
        "comment": _with_admin_prefix(comment_body, admin_tag),
    })
    items = await _fetch_items_by_ids([item_id])
    if items:
        await _send_tg(_msg_reserve_set(items[0], reserve_date, admin_tag, comment_body))
    notify_inventory_changed()
    return {"ok": True, "reserve_date": reserve_date}


@router.delete("/reserves/{item_id}")
async def reserves_delete(
        item_id: int,
        data: dict | None = Body(None),
        reason_q: str | None = Query(None),
):
    reason = (data or {}).get("reason") or (reason_q or "")

    # взять карточку ДО смены статуса
    items = await _fetch_items_by_ids([item_id])

    # снять резерв
    await _change_status([item_id], status=0, options={})

    # уведомить чат
    try:
        if items:
            await _send_tg(_msg_reserve_cancel(items[0], admin_tag=None, reason=reason))
        else:
            p = next((p for p in PRODUCTS if int(p.id) == int(item_id)), None)
            if p:
                await _send_tg(_msg_reserve_cancel_from_product(p, reason))
            else:
                txt = f"🔴 <b>Снят резерв</b> — ID {item_id}"
                if reason.strip():
                    txt += f"\n<b>Причина:</b> {html.escape(reason)}"
                await _send_tg(txt)
    except Exception as e:
        print("reserve delete notify error:", e, flush=True)

    notify_inventory_changed()
    return {"ok": True}


# алиас, если фронт шлёт POST вместо DELETE
@router.post("/reserves/remove")
async def reserves_delete_alias(item_id: int = Body(..., embed=True),
                                reason: str = Body("", embed=True)):
    return await reserves_delete(item_id=item_id, data={"reason": reason})
