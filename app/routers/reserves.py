import re
import html
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Body, BackgroundTasks
from sqlalchemy.orm import Session
import httpx
from aiogram import Bot

from ..db import get_db
from ..loaders import refresh_from_api
from ..models import User
from ..security import validate_init_data, extract_tg_id
from ..config import settings

router = APIRouter(prefix="/api/reserves", tags=["reserves"])

AVAX_ALL_URL = "https://avax.by/api/all_reserves/DueMQ88!Sm43"
AVAX_SET_URL = "https://avax.by/api/set_reserve/DueMQ88!Sm43"
AVAX_REMOVE_URL = "https://avax.by/api/remove_reserve/DueMQ88!Sm43/"

CHAT_ID = -1001811638529
THREAD_EDIT = 14  # тред для уведомлений по резервам

ADMIN_RX = re.compile(r'^\s*\[admin:\s*([^\]]+)\]\s*(.*)$', re.I)


def _check_admin(tg_id: str, db: Session) -> User:
    u = db.query(User).filter(User.tg_id == tg_id).first()
    if not u or not (u.is_admin or str(tg_id) == str(settings.admin_id)):
        raise HTTPException(status_code=403, detail="forbidden")
    return u


async def _avax_all() -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as cli:
        r = await cli.get(AVAX_ALL_URL)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        return data


def _split_admin_comment(full: str | None) -> tuple[str | None, str]:
    """Возвращает (admin_tag, user_comment)."""
    s = (full or "").strip()
    m = ADMIN_RX.match(s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, s


def _join_admin_comment(admin_tag: str | None, user_comment: str) -> str:
    uc = (user_comment or "").strip()
    if admin_tag:
        return f"[admin: {admin_tag}] {uc}".strip()
    return uc


def _map_row(row: dict[str, Any]) -> dict[str, Any]:
    cid = int(row.get("id"))
    brand = (row.get("МАРКА") or "").strip()
    model = (row.get("МОДЕЛЬ") or "").strip()
    year = str(row.get("ГОД") or "").strip()
    part = (row.get("ЗАПЧАСТЬ") or "").strip()
    till = (row.get("Резерв до") or "").strip()
    comment_full = (row.get("Комментарий резерва") or "").strip()
    admin_tag, user_comment = _split_admin_comment(comment_full)
    engine_mark = (row.get("МАРКИРОВКА ДВИГАТЕЛЯ") or "").strip()
    razbor = " ".join(
        x for x in [(row.get("ШРОТ") or "").strip(), (row.get("ВХОДНОЙ АРТИКУЛ") or "").strip()] if x
    ).strip()
    photos = [x.strip() for x in (row.get("ФОТО") or "").split(",") if x.strip()]
    return {
        "id": cid,
        "brand": brand,
        "model": model,
        "year": year,
        "part": part,
        "till": till,
        "comment_full": comment_full,
        "admin_tag": admin_tag,
        "user_comment": user_comment,
        "engine_mark": engine_mark,
        "razbor": razbor,
        "price": row.get("ЦЕНА") or "",
        "currency": (row.get("ВАЛЮТА") or "").strip(),
        "warehouse": (row.get("Склад") or "").strip(),
        "photos": photos,
        "raw": row,
    }


async def _send_tg(text: str, thread_id: int):
    bot = Bot(settings.bot_token)
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            message_thread_id=thread_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    finally:
        await bot.session.close()


# ---------- API ----------

@router.get("/admins")
async def admins(init_data: str, db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    rows = await _avax_all()
    counts: dict[str, int] = {}
    unknown = 0
    for r in rows:
        tag, _ = _split_admin_comment(r.get("Комментарий резерва"))
        if tag:
            counts[tag] = counts.get(tag, 0) + 1
        else:
            unknown += 1
    items = [{"tag": k, "label": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
    return {"items": items, "unknown": unknown}


@router.get("")
async def list_reserves(
        init_data: str,
        tag: str | None = Query(None, description="admin_tag из [admin: ...]"),
        unknown: int | None = Query(None, description="1 — только без admin_tag"),
        db: Session = Depends(get_db),
):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    rows = await _avax_all()
    out = []
    for r in rows:
        item = _map_row(r)
        if tag:
            if item["admin_tag"] == tag:
                out.append(item)
        elif unknown:
            if not item["admin_tag"]:
                out.append(item)
        else:
            out.append(item)
    # порядок — новые сверху (по id)
    out.sort(key=lambda x: x["id"], reverse=True)
    return {"items": out}


@router.get("/{zap}")
async def one_reserve(zap: int, init_data: str, db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    rows = await _avax_all()
    for r in rows:
        try:
            if int(r.get("id")) == zap:
                return _map_row(r)
        except Exception:
            pass
    raise HTTPException(404, "not found")


@router.patch("/{zap}/comment")
async def edit_comment(
        zap: int,
        init_data: str = Body(..., embed=True),
        comment: str = Body(..., embed=True, description="новый пользовательский комментарий (без префикса admin)"),
        admin_tag: str | None = Body(None, embed=True),
        db: Session = Depends(get_db),
        background_tasks: BackgroundTasks = None,
):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(401, "user missing")
    u = _check_admin(tg_id, db)
    editor_name = (u.name or "").strip() or str(tg_id)

    # если admin_tag не передали — достанем из текущего резерва
    if not admin_tag:
        rows = await _avax_all()
        for r in rows:
            try:
                if int(r.get("id")) == zap:
                    old_tag, old_user_comment = _split_admin_comment(r.get("Комментарий резерва"))
                    admin_tag = old_tag
                    before = old_user_comment
                    break
            except Exception:
                continue
        else:
            raise HTTPException(404, "not found")
    else:
        # также достанем before для уведомления
        rows = await _avax_all()
        before = ""
        for r in rows:
            try:
                if int(r.get("id")) == zap:
                    _, old_user_comment = _split_admin_comment(r.get("Комментарий резерва"))
                    before = old_user_comment
                    break
            except Exception:
                continue

    new_full = _join_admin_comment(admin_tag, comment)

    # Обновляем резерв на стороне Avax: по аналогии с set_reserve
    till = date.today().isoformat()
    async with httpx.AsyncClient(timeout=20) as cli:
        r = await cli.post(AVAX_SET_URL, data={"comment": new_full, "till": till, "zap": str(zap)})
        if r.status_code >= 400:
            raise HTTPException(503, "remote error")

    # Уведомление в тред (только комментарии до/после, БЕЗ имени того, кто ставил; имя редактора оставляем отдельно)
    txt = (
        "✏️ <b>Изменение комментария резерва</b>\n"
        f"<b>До:</b> “{html.escape(before or '')}”\n"
        f"<b>После:</b> “{html.escape(comment or '')}”\n"
        f"<i>Редактировал: {html.escape(editor_name)}</i>"
    )
    if background_tasks is not None:
        background_tasks.add_task(_send_tg, txt, THREAD_EDIT)
    else:
        await _send_tg(txt, THREAD_EDIT)

    return {"ok": True}


@router.delete("/{zap}")
async def delete_reserve(
        zap: int,
        init_data: str = Body(..., embed=True),
        db: Session = Depends(get_db),
        background_tasks: BackgroundTasks = None,
):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    # Avax ждёт form-data: {"zap": id}
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.post(AVAX_REMOVE_URL.rstrip("/"), data={"zap": str(zap)})
            if r.status_code >= 400:
                raise HTTPException(503, "remote error")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "remote error")

    # форс-рефреш склада, чтобы витрина и списки обновились
    try:
        await refresh_from_api(force=True)
    except Exception as e:
        print("force refresh after reserve remove failed:", e)

    # по желанию можно уведомлять в тред:
    # msg = f"🗑 <b>Резерв снят</b> — id:{zap}"
    # if background_tasks: background_tasks.add_task(_send_tg, msg, THREAD_EDIT)
    # else: await _send_tg(msg, THREAD_EDIT)

    return {"ok": True}
