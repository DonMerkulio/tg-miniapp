import logging
import html
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from aiogram import Bot

from ..db import get_db
from ..models import Shipment, User
from ..security import validate_init_data, extract_tg_id
from ..config import settings

router = APIRouter(prefix="/api/shipments", tags=["shipments"])

logger = logging.getLogger("shipments")


# ----------------------------- helpers -----------------------------
def _check_admin(tg_id: str, db: Session):
    u = db.query(User).filter(User.tg_id == tg_id).first()
    if not u or not (u.is_admin or str(tg_id) == str(settings.admin_id)):
        raise HTTPException(status_code=403, detail="forbidden")


def _to_dict(sh: Shipment) -> dict:
    return {
        "id": sh.id,
        "category": sh.category,
        "articles": sh.articles,
        "warehouse": sh.warehouse,
        "carrier": sh.carrier,
        "city": sh.city,
        "client_info": sh.client_info,
        "prepay": sh.prepay,
        "created_at": sh.created_at.isoformat(),
        "track_no": (sh.track_no or ""),
        "is_sent": sh.is_sent,
        "created_by": sh.created_by,
    }


async def _send_tg(text: str, thread_id: int):
    bot = Bot(settings.bot_token)
    try:
        await bot.send_message(
            chat_id=-1001811638529,
            message_thread_id=thread_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception("telegram send failed: %s", e)
    finally:
        await bot.session.close()


def _notify_track(sh: Shipment, background_tasks: BackgroundTasks):
    track = (sh.track_no or "").strip()
    if not track:
        return
    txt = (
        "📦 <b>Трек-номер добавлен</b>\n"
        f"<b>ID:</b> {sh.id}\n"
        f"<b>Категория:</b> {html.escape(sh.category)}\n"
        f"<b>Артикул(а):</b> {html.escape(sh.articles)}\n"
        f"<b>Склад:</b> {html.escape(sh.warehouse)}\n"
        f"<b>ТК:</b> {html.escape(sh.carrier)}\n"
        f"<b>Город:</b> {html.escape(sh.city)}\n"
        f"<b>Клиент:</b> {html.escape(sh.client_info)}\n"
        f"<b>На клиента:</b> {'Да' if sh.prepay else 'Нет'}\n"
        f"<b>Трек:</b> {html.escape(track)}\n"
        f"<b>Кто создал:</b> {html.escape(sh.created_by)}"
    )
    background_tasks.add_task(_send_tg, txt, 6)


def _notify_sent(sh: Shipment, background_tasks: BackgroundTasks):
    """Уведомление при пометке заявки как отправленной."""
    txt = (
        "✅ <b>Отправлено</b>\n"
        f"<b>ID:</b> {sh.id}\n"
        f"<b>Категория:</b> {html.escape(sh.category)}\n"
        f"<b>Артикул(а):</b> {html.escape(sh.articles)}\n"
        f"<b>Склад:</b> {html.escape(sh.warehouse)}\n"
        f"<b>ТК:</b> {html.escape(sh.carrier)}\n"
        f"<b>Город:</b> {html.escape(sh.city)}\n"
        f"<b>Клиент:</b> {html.escape(sh.client_info)}\n"
        f"<b>На клиента:</b> {'Да' if sh.prepay else 'Нет'}\n"
        f"<b>Трек:</b> {html.escape(sh.track_no or '—')}\n"
        f"<b>Кто создал:</b> {html.escape(sh.created_by)}"
    )
    background_tasks.add_task(_send_tg, txt, 6)


def _notify_diff(before: dict, after: dict, background_tasks: BackgroundTasks):
    # Человеческие лейблы
    LABELS = {
        "id": "ID",
        "category": "Категория",
        "articles": "Артикул(а)",
        "warehouse": "Склад",
        "carrier": "ТК",
        "city": "Город",
        "client_info": "Клиент",
        "prepay": "На клиента",
        "track_no": "Трек",
        "is_sent": "Статус отправки",
        "created_by": "Кто создал",
        "created_at": "Дата создания",
    }

    def _fmt(field: str, v: str) -> str:
        if field == "prepay":
            return "Да" if (str(v).lower() in {"true", "1", "yes", "да"}) else "Нет"
        return v

    lines = [f"✏️ <b>Изменение отправки #{after.get('id')}</b>"]
    for f in sorted(set(before) | set(after)):
        b = str(before.get(f, "")).strip()
        a = str(after.get(f, "")).strip()
        if b != a:
            title = LABELS.get(f, f)
            b2 = html.escape(_fmt(f, b))
            a2 = html.escape(_fmt(f, a))
            lines.append(f"<b>{title}:</b> “{b2}” → “{a2}”")

    if len(lines) > 1:
        background_tasks.add_task(_send_tg, "\n".join(lines), 6)


# ----------------------------- routes -----------------------------
@router.post("")
def create(
    background_tasks: BackgroundTasks,
    init_data: str = Body(..., embed=True),
    category: str = Body(..., embed=True),
    articles: str = Body(..., embed=True),
    warehouse: str = Body(..., embed=True),  # "москва" | "озеро"
    carrier: str = Body(..., embed=True),
    city: str = Body(..., embed=True),
    client_info: str = Body(..., embed=True),
    prepay: bool = Body(False, embed=True),
    track_no: str = Body("", embed=True),
    db: Session = Depends(get_db),
):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    # имя пользователя для "кто создал"
    u = db.query(User).filter(User.tg_id == tg_id).first()
    created_by = (u.name or "").strip() if u and (u.name or "").strip() else str(tg_id)

    sh = Shipment(
        category=category.strip(),
        articles=articles.strip(),
        warehouse=warehouse.strip().lower(),
        carrier=carrier.strip(),
        city=city.strip(),
        client_info=client_info.strip(),
        prepay=bool(prepay),
        track_no=(track_no or "").strip(),
        is_sent=False,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )
    db.add(sh)
    db.commit()
    db.refresh(sh)

    _notify_track(sh, background_tasks)  # отправим, если трек сразу указан
    return {"ok": True, "item": _to_dict(sh)}


@router.get("")
def list_active(
    init_data: str,
    warehouse: str | None = Query(None),  # "москва"/"озеро" или None
    db: Session = Depends(get_db),
):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    q = db.query(Shipment).filter(Shipment.is_sent == False)
    if warehouse:
        q = q.filter(Shipment.warehouse == warehouse.lower())
    items = q.order_by(Shipment.created_at.desc()).all()
    return {"items": [_to_dict(x) for x in items]}


@router.get("/{sid}")
def get_one(sid: int, init_data: str, db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    sh = db.query(Shipment).get(sid)
    if not sh:
        raise HTTPException(404, "not found")
    return _to_dict(sh)


@router.patch("/{sid}")
def update(
    sid: int,
    background_tasks: BackgroundTasks,
    init_data: str = Body(..., embed=True),
    payload: dict = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    sh = db.query(Shipment).get(sid)
    if not sh:
        raise HTTPException(404, "not found")

    before = _to_dict(sh)

    for k in ["category", "articles", "warehouse", "carrier", "city", "client_info", "prepay", "track_no", "is_sent"]:
        if k in payload:
            setattr(sh, k, payload[k] if k != "warehouse" else str(payload[k]).lower())

    db.commit()
    db.refresh(sh)

    after = _to_dict(sh)

    # diff
    _notify_diff(before, after, background_tasks)

    # уведомление о треке (если стал непустым и изменился)
    if (before.get("track_no", "").strip() != after.get("track_no", "").strip()) and after.get("track_no", "").strip():
        _notify_track(sh, background_tasks)

    return {"ok": True, "item": after}


@router.post("/{sid}/mark_sent")
def mark_sent(
    sid: int,
    background_tasks: BackgroundTasks,
    init_data: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    sh = db.query(Shipment).get(sid)
    if not sh:
        raise HTTPException(404, "not found")

    if not sh.is_sent:
        sh.is_sent = True
        db.commit()
        db.refresh(sh)
        _notify_sent(sh, background_tasks)

    return {"ok": True}


@router.delete("/{sid}")
def delete(sid: int, init_data: str = Body(..., embed=True), db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(401, "user missing")
    _check_admin(tg_id, db)

    sh = db.query(Shipment).get(sid)
    if not sh:
        raise HTTPException(404, "not found")
    db.delete(sh)
    db.commit()
    return {"ok": True}
