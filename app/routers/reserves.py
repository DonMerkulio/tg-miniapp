from __future__ import annotations
import re, html
from datetime import datetime, timedelta, timezone
import httpx
from fastapi import APIRouter, Query, Body, HTTPException
from aiogram import Bot
from ..config import settings
from .realtime import notify_inventory_changed

router = APIRouter(prefix="/api", tags=["reserves"])

LIST_URL = f"{settings.api_base}/api/items.php?action=list&limit=10000&with_photo=1&filters[stock_status]=2"
# наверху файла
ADMIN_RE = re.compile(r"^\s*\[admin:\s*([^\(]+?)\s*\((\d+)\)\]\s*", re.IGNORECASE)
MSK = timezone(timedelta(hours=3))

from ..db import SessionLocal
from ..models import User

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


def _with_admin_prefix(comment: str, admin_tag: str | None) -> str:
    # убираем старый префикс и, если задан, добавляем нужный
    body = ADMIN_RE.sub("", (comment or "").strip())
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


def _msk_plus_days_ymd(days: int = 4) -> str:
    return (datetime.now(MSK) + timedelta(days=days)).strftime("%Y-%m-%d")


def _strip_admin_prefix(comment: str) -> str:
    return ADMIN_RE.sub("", (comment or "").strip()).strip()


def _with_admin_prefix(comment: str, admin_tag: str | None) -> str:
    body = _strip_admin_prefix(comment)
    tag = (admin_tag or "").strip()
    return f"{tag} {body}".strip() if tag else body


async def _fetch_items_by_ids(ids: list[int]) -> list[dict]:
    url = f"{settings.api_base}/api/items.php"
    params = [("action", "list"), ("with_photo", "0")]
    for i in ids:
        params.append(("ids[]", str(int(i))))
    async with httpx.AsyncClient(timeout=25) as cli:
        r = await cli.get(url, params=params)
        r.raise_for_status()
        j = r.json()
        return (j or {}).get("data", {}).get("items", []) if isinstance(j, dict) else []


def _fields(item: dict) -> dict:
    f = item.get("fields") or {}
    g = lambda key, sub="display_value": (f.get(key, {}) or {}).get(sub) or ""
    v = lambda key: (f.get(key, {}) or {}).get("value") or ""
    brand = g("car_brand_id");
    model = g("car_model_id");
    part = g("part_id");
    year = v("year")
    capacity = g("capacity_id");
    fuel = g("type_id");
    engine_mark = v("mark_engine")
    warehouse = g("stock_id")
    shrot = g("shrot_id");
    input_article = v("input_article")
    articles = " ".join(x for x in [shrot, input_article] if x).strip()
    return dict(brand=brand, model=model, part=part, year=str(year).strip(),
                capacity=capacity, fuel=fuel, engine_mark=engine_mark,
                warehouse=warehouse, articles=articles)


async def _send_tg(text: str) -> None:
    bot = Bot(settings.bot_token)
    try:
        kwargs = dict(chat_id=settings.notify_chat_id_reserve,
                      text=text, parse_mode="HTML",
                      disable_web_page_preview=True)
        if settings.notify_thread_id_reserve:
            kwargs["message_thread_id"] = int(settings.notify_thread_id_reserve)
        await bot.send_message(**kwargs)
    finally:
        await bot.session.close()


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


def _msg_reserve_set(item: dict, reserve_date: str, admin_tag: str | None, comment: str) -> str:
    f = _fields(item)
    title = f"{(f['brand'] or '').strip()} {(f['model'] or '').strip()}".strip()
    lines = []

    def add(lbl, val):
        v = (val or "").strip()
        if v: lines.append(f"<b>{html.escape(lbl)}:</b> {html.escape(v)}")

    add("Запчасть", f["part"])
    add("Год", f["year"])
    if f["capacity"] or f["fuel"]: add("Двигатель", f"{f['capacity']} {f['fuel']}".strip())
    add("Маркировка дв.", f["engine_mark"])
    add("На складе", f["warehouse"])
    add("Разборочный", f["articles"])
    add("Резерв до", reserve_date)
    if admin_tag: add("Админ", _strip_admin_prefix(admin_tag))
    if comment: add("Комментарий", _strip_admin_prefix(comment))
    header = f"🟡 <b>Резерв</b> — {html.escape(title)}"
    return header + "\n" + "\n".join(lines)


def _msg_reserve_cancel(item: dict, admin_tag: str | None, reason: str | None) -> str:
    f = _fields(item)
    title = f"{(f['brand'] or '').strip()} {(f['model'] or '').strip()}".strip()
    lines = []

    def add(lbl, val):
        v = (val or "").strip()
        if v: lines.append(f"<b>{html.escape(lbl)}:</b> {html.escape(v)}")

    add("Запчасть", f["part"])
    add("Год", f["year"])
    add("На складе", f["warehouse"])
    add("Разборочный", f["articles"])
    if admin_tag: add("Админ", _strip_admin_prefix(admin_tag))
    if reason: add("Причина", reason)
    header = f"🔴 <b>Снят резерв</b> — {html.escape(title)}"
    return header + "\n" + "\n".join(lines)


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

    shrot = (f.get("shrot_id", {}).get("display_value") or "").strip()
    input_article = (f.get("input_article", {}).get("value") or "").strip()
    articles = " ".join(x for x in [shrot, input_article] if x).strip()

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

        # отдаем «чистый» комментарий
        "comment": user_comment,
        "user_comment": user_comment,

        # данные об админе отдельно
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
            g["name"] = shown_name  # на случай если впервые был плейсхолдер
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
    # старые фронтовые параметры
    if unknown:
        admin = "_"
    if tag and not admin:
        # tag может быть вида: "[admin: Имя (565032824)]"
        m = ADMIN_RE.search(tag)
        if m:
            admin = m.group(2)  # tg_id
    return await reserves_list(admin=admin)


@router.patch("/reserves/{item_id}/comment")
async def reserves_update_comment(item_id: int, data: dict = Body(...)):
    # приходят: comment, admin_tag (init_data игнорим)
    admin_tag = data.get("admin_tag") or ""
    comment_body = data.get("comment") or ""
    reserve_date = (data.get("reserve_date") or _msk_plus_days_ymd())
    # 1) смена статуса
    await _change_status([item_id], status=2, options={
        "reserve_date": reserve_date,
        "comment": _with_admin_prefix(comment_body, admin_tag),
    })
    # 2) загрузим карточку и уведомим TG
    items = await _fetch_items_by_ids([item_id])
    if items:
        await _send_tg(_msg_reserve_set(items[0], reserve_date, admin_tag, comment_body))
    notify_inventory_changed()
    return {"ok": True, "reserve_date": reserve_date}


@router.delete("/reserves/{item_id}")
async def reserves_delete(item_id: int, data: dict | None = Body(None)):
    reason = (data or {}).get("reason") or ""
    # возьмем данные ДО изменения статуса, чтобы красиво сообщить
    items = await _fetch_items_by_ids([item_id])
    # 1) вернуть на склад
    await _change_status([item_id], status=0, options={})
    # 2) уведомление TG
    if items:
        await _send_tg(_msg_reserve_cancel(items[0], admin_tag=None, reason=reason))
    notify_inventory_changed()
    return {"ok": True}
