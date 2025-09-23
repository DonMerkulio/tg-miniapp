from __future__ import annotations
import asyncio, time, uuid
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Body, Query, BackgroundTasks
from sqlalchemy.orm import Session

from aiogram import Bot
from aiogram.types import BufferedInputFile
from aiogram import exceptions as tg_exc

from ..db import get_db, SessionLocal
from ..models import User
from ..security import validate_init_data, extract_tg_id
from ..config import settings
from ..exports import build_prices_xlsx
from ..loaders import PRODUCTS, RESERVED_IDS

router = APIRouter(prefix="/api/broadcast", tags=["broadcast"])

def _check_admin(tg_id: str, db: Session):
    u = db.query(User).filter(User.tg_id == tg_id).first()
    if not u or not (u.is_admin or str(tg_id) == str(settings.admin_id)):
        raise HTTPException(status_code=403, detail="forbidden")

# --- состояние рассылок ---
JOBS: Dict[str, Dict[str, Any]] = {}

def _pick_recipients(db: Session) -> List[User]:
    return (
        db.query(User)
        .filter(User.notifications == True, User.is_blocked == False)
        .order_by(User.created_at.asc())
        .all()
    )

def _build_files() -> Dict[str, bytes]:
    avail = [p for p in PRODUCTS if p.id not in RESERVED_IDS]  # исключаем резервы

    engines  = [p for p in avail if (p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ") or "").strip() == "Двигатель"]
    nosecuts = [p for p in avail if (p.__dict__.get("_raw", {}).get("ЗАПЧАСТЬ") or "").strip() == "Передняя часть (ноускат) в сборе"]
    ids_eng, ids_nose = {p.id for p in engines}, {p.id for p in nosecuts}
    others = [p for p in avail if p.id not in (ids_eng | ids_nose)]

    out: Dict[str, bytes] = {}
    if engines:  out["Двигатели.xlsx"]       = build_prices_xlsx(engines).getvalue()
    if nosecuts: out["Ноускаты.xlsx"]        = build_prices_xlsx(nosecuts).getvalue()
    if others:   out["Прочие запчасти.xlsx"] = build_prices_xlsx(others).getvalue()
    return out

TEXT = (
    "✨ <b>Новое поступление на складах</b>\n"
    "Свежие позиции в Москве и Озере. Прайсы во вложении — смотрите актуальную стоимость и наличие.\n\n"
)

def _reason_from_exc(e: Exception) -> str:
    s = (str(e) or "").lower()
    if isinstance(e, tg_exc.TelegramForbiddenError) or "blocked by the user" in s:
        return "пользователь заблокировал бота"
    if "deactivated" in s:
        return "аккаунт удалён/деактивирован"
    if isinstance(e, tg_exc.TelegramBadRequest) and ("chat not found" in s or "user not found" in s):
        return "чат/пользователь не найден"
    if isinstance(e, tg_exc.TelegramRetryAfter) or "too many requests" in s:
        return "слишком много запросов (лимит Telegram)"
    return str(e) or "ошибка доставки"

async def _run_job(job_id: str, user_ids: List[int]) -> None:
    JOBS[job_id]["started_at"] = time.time()
    files = _build_files()
    bot = Bot(settings.bot_token)
    try:
        for uid in user_ids:
            if JOBS.get(job_id, {}).get("cancel"):
                break
            try:
                await bot.send_message(int(uid), TEXT, parse_mode="HTML", disable_web_page_preview=True)
                for name, data in files.items():
                    await bot.send_document(int(uid), BufferedInputFile(data, filename=name))
                JOBS[job_id]["sent"] += 1
            except Exception as e:
                # достаём инфо о пользователе, фиксируем причину
                reason = _reason_from_exc(e)
                try:
                    with SessionLocal() as s:
                        u = s.query(User).filter(User.tg_id == str(uid)).first()
                        if u:
                            JOBS[job_id]["fails"].append({
                                "tg_id": str(uid),
                                "name": u.name or "",
                                "phone": u.phone or "",
                                "reason": reason,
                                "blocked": True
                            })
                            # блокируем и выключаем уведомления
                            u.notifications = False
                            u.is_blocked = True
                            s.commit()
                        else:
                            JOBS[job_id]["fails"].append({
                                "tg_id": str(uid),
                                "name": "",
                                "phone": "",
                                "reason": reason,
                                "blocked": True
                            })
                except Exception:
                    JOBS[job_id]["fails"].append({
                        "tg_id": str(uid),
                        "name": "",
                        "phone": "",
                        "reason": reason,
                        "blocked": True
                    })
            finally:
                JOBS[job_id]["processed"] += 1
                await asyncio.sleep(0.2)
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
        JOBS[job_id]["done"] = True

@router.get("/prices/recipients")
def recipients(init_data: str = Query(...), db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    _check_admin(tg_id, db)
    recips = _pick_recipients(db)
    return {"count": len(recips)}

@router.post("/prices/start")
def start(
    background_tasks: BackgroundTasks,
    init_data: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    _check_admin(tg_id, db)

    recips = _pick_recipients(db)
    user_ids = [int(u.tg_id) for u in recips if str(u.tg_id).isdigit()]

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"total": len(user_ids), "sent": 0, "processed": 0, "fails": [], "done": False}

    background_tasks.add_task(_run_job, job_id, user_ids)
    return {"job_id": job_id, "total": len(user_ids)}

@router.get("/prices/status")
def status(job_id: str):
    st = JOBS.get(job_id)
    if not st: raise HTTPException(404, "job not found")
    return {
        "total": st["total"],
        "sent": st["sent"],
        "processed": st["processed"],
        "failed_count": len(st["fails"]),
        "failed": st["fails"],
        "done": st["done"],
    }
