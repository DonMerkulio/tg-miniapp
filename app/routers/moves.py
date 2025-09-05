from fastapi import APIRouter, Body, HTTPException, Depends, Query, Path
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Move, User
from ..security import validate_init_data, extract_tg_id
from ..config import settings
from aiogram import Bot
from datetime import datetime
import anyio, html

router = APIRouter(prefix="/api/moves", tags=["moves"])

CHAT_ID = -1001811638529
THREAD_ID = 13

def _check_admin(tg_id: str, db: Session):
    u = db.query(User).filter(User.tg_id == tg_id).first()
    if not u or not (u.is_admin or str(tg_id) == str(settings.admin_id)):
        raise HTTPException(status_code=403, detail="forbidden")

def _cap_wh(v: str) -> str:
    v = (v or "").strip().lower()
    return "Москва" if v == "москва" else "Озеро"

def _route_str(f: str, t: str) -> str:
    return f"{_cap_wh(f)} → {_cap_wh(t)}"

def _to_dict(m: Move) -> dict:
    return {
        "id": m.id,
        "part": m.part,
        "articles": m.articles,
        "from_wh": m.from_wh,
        "to_wh": m.to_wh,
        "created_at": m.created_at.isoformat(),
        "is_done": m.is_done,
        "created_by": m.created_by,
    }

async def _send_message(txt: str):
    bot = Bot(settings.bot_token)
    try:
        await bot.send_message(chat_id=CHAT_ID, message_thread_id=THREAD_ID,
                               text=txt, parse_mode="HTML", disable_web_page_preview=True)
    finally:
        await bot.session.close()

@router.post("")
def create(
    init_data: str = Body(..., embed=True),
    part: str = Body(..., embed=True),
    articles: str = Body(..., embed=True),
    from_wh: str | None = Body(None, embed=True),
    to_wh: str | None   = Body(None, embed=True),
    route: str | None   = Body(None, embed=True),
    db: Session = Depends(get_db)
):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id: raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    # маршрут ...
    f, t = (from_wh or "").strip().lower(), (to_wh or "").strip().lower()
    if route:
        rv = route.strip().lower()
        if rv == "озеро-москва": f, t = "озеро", "москва"
        elif rv == "москва-озеро": f, t = "москва", "озеро"
    if f not in {"москва","озеро"} or t not in {"москва","озеро"} or f == t:
        raise HTTPException(400, "invalid route")

    # ✨ имя создателя
    u = db.query(User).filter(User.tg_id == tg_id).first()
    creator_name = (u.name or "").strip() if u else ""

    m = Move(
        part=part.strip(),
        articles=articles.strip(),
        from_wh=f, to_wh=t,
        created_by=creator_name or str(tg_id),  # <= сохраняем имя (fallback: tg_id)
        created_at=datetime.utcnow(),
        is_done=False
    )
    db.add(m); db.commit(); db.refresh(m)

    txt = (
        "🔁 <b>Перемещение создано</b>\n"
        f"<b>ID:</b> {m.id}\n"
        f"<b>Запчасть:</b> {html.escape(m.part)}\n"
        f"<b>Артикул(а):</b> {html.escape(m.articles)}\n"
        f"<b>Маршрут:</b> {_route_str(m.from_wh, m.to_wh)}\n"
        f"<b>Создано:</b> {m.created_at:%Y-%m-%d %H:%M}\n"
        f"<b>Создал:</b> {html.escape(m.created_by)}"  # <= теперь имя
    )
    anyio.from_thread.run(_send_message, txt)

    return {"ok": True, "item": _to_dict(m)}

@router.get("")
def list_active(
    init_data: str,
    to: str | None = Query(None, description="фильтр по пункту назначения: москва/озеро"),
    db: Session = Depends(get_db)
):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id: raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    q = db.query(Move).filter(Move.is_done == False)
    if to and to.strip().lower() in {"москва","озеро"}:
        q = q.filter(Move.to_wh == to.strip().lower())
    items = q.order_by(Move.created_at.desc()).all()
    return {"items": [_to_dict(x) for x in items]}

@router.get("/{mid}")
def get_one(mid: int, init_data: str, db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id: raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    m = db.query(Move).get(mid)
    if not m: raise HTTPException(404, "not found")
    return _to_dict(m)

@router.patch("/{mid}")
def update(
    mid: int,
    init_data: str = Body(..., embed=True),
    payload: dict = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id: raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    m = db.query(Move).get(mid)
    if not m: raise HTTPException(404, "not found")

    before = _to_dict(m)

    if "part" in payload:     m.part = str(payload["part"]).strip()
    if "articles" in payload: m.articles = str(payload["articles"]).strip()

    # можно передать from_wh/to_wh напрямую или route
    if "route" in payload:
        rv = str(payload["route"]).strip().lower()
        if rv == "озеро-москва": m.from_wh, m.to_wh = "озеро", "москва"
        elif rv == "москва-озеро": m.from_wh, m.to_wh = "москва", "озеро"
    if "from_wh" in payload:
        m.from_wh = str(payload["from_wh"]).strip().lower()
    if "to_wh" in payload:
        m.to_wh = str(payload["to_wh"]).strip().lower()

    db.commit(); db.refresh(m)

    after = _to_dict(m)

    # Уведомление: diff
    LABELS = {
        "part":"Запчасть","articles":"Артикул(а)","from_wh":"Откуда","to_wh":"Куда",
        "is_done":"Статус","created_by":"Кто создал","created_at":"Дата создания","id":"ID"
    }
    def _val(field: str, v: str) -> str:
        if field in {"from_wh","to_wh"}:
            return _cap_wh(v)
        return str(v)

    lines = [f"✏️ <b>Изменение перемещения #{m.id}</b>"]
    # Если изменился маршрут — одной строкой
    if (before["from_wh"] != after["from_wh"]) or (before["to_wh"] != after["to_wh"]):
        lines.append(f"<b>Маршрут:</b> “{html.escape(_route_str(before['from_wh'], before['to_wh']))}” на "
                     f"“{html.escape(_route_str(after['from_wh'], after['to_wh']))}”")
    for f in ("part","articles"):
        b, a = _val(f, before.get(f,"")), _val(f, after.get(f,""))
        if b != a:
            lines.append(f"<b>{html.escape(LABELS.get(f,f))}:</b> “{html.escape(b)}” → “{html.escape(a)}”")

    if len(lines) > 1:
        anyio.from_thread.run(_send_message, "\n".join(lines))

    return {"ok": True, "item": _to_dict(m)}

@router.post("/{mid}/mark_done")
def mark_done(mid: int, init_data: str = Body(..., embed=True), db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id: raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    m = db.query(Move).get(mid)
    if not m: raise HTTPException(404, "not found")
    m.is_done = True
    db.commit(); db.refresh(m)

    txt = f"✅ <b>Перемещение #{m.id} завершено</b> — {_route_str(m.from_wh, m.to_wh)}"
    anyio.from_thread.run(_send_message, txt)

    return {"ok": True}

@router.delete("/{mid}")
def delete(mid: int, init_data: str = Body(..., embed=True), db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id: raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    m = db.query(Move).get(mid)
    if not m: raise HTTPException(404, "not found")
    db.delete(m); db.commit()
    return {"ok": True}
