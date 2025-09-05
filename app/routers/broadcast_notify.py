from __future__ import annotations
import asyncio, time, uuid
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form, Query
from sqlalchemy.orm import Session

from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto, InputMediaVideo
from aiogram import exceptions as tg_exc

from ..db import get_db, SessionLocal
from ..models import User
from ..security import validate_init_data, extract_tg_id
from ..config import settings

router = APIRouter(prefix="/api/broadcast/notify", tags=["broadcast-notify"])

# -------- helpers --------
def _check_admin(tg_id: str, db: Session):
    u = db.query(User).filter(User.tg_id == tg_id).first()
    if not u or not (u.is_admin or str(tg_id) == str(settings.admin_id)):
        raise HTTPException(status_code=403, detail="forbidden")

def _pick_recipients(db: Session) -> List[User]:
    return (
        db.query(User)
        .filter(User.notifications == True, User.is_blocked == False)
        .order_by(User.created_at.asc())
        .all()
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

# -------- state --------
JOBS: Dict[str, Dict[str, Any]] = {}

# -------- preview --------
@router.post("/preview")
async def preview(
    init_data: str = Form(...),
    text: str = Form(""),
    photos: List[UploadFile] = File(default=[]),
    files:  List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    _check_admin(tg_id, db)

    # прочитать вложения
    album_bytes: List[tuple[str, bytes, str]] = []  # (name, data, kind: 'photo'|'video')
    docs_bytes:  List[tuple[str, bytes]] = []       # (name, data)

    # фото (только image/*)
    for f in photos[:10]:
        if not (f.content_type or "").startswith("image/"): continue
        album_bytes.append((f.filename or "photo.jpg", await f.read(), "photo"))

    # файлы/видео (до 5)
    for f in files[:5]:
        ct = f.content_type or ""
        data = await f.read()
        if ct.startswith("video/"):
            # видео можно в альбом
            if len(album_bytes) < 10:
                album_bytes.append((f.filename or "video.mp4", data, "video"))
        else:
            docs_bytes.append((f.filename or "file.bin", data))

    # отправка
    bot = Bot(settings.bot_token)
    try:
        if (text or "").strip():
            await bot.send_message(int(tg_id), text, parse_mode="HTML", disable_web_page_preview=True)
        # альбом (фото/видео)
        if album_bytes:
            media = []
            for name, data, kind in album_bytes[:10]:
                if kind == "video":
                    media.append(InputMediaVideo(media=BufferedInputFile(data, filename=name)))
                else:
                    media.append(InputMediaPhoto(media=BufferedInputFile(data, filename=name)))
            await bot.send_media_group(int(tg_id), media)
        # документы
        for name, data in docs_bytes[:5]:
            await bot.send_document(int(tg_id), BufferedInputFile(data, filename=name))
    finally:
        try: await bot.session.close()
        except: pass

    return {"ok": True}

# -------- start --------
@router.get("/recipients")
def recipients(init_data: str = Query(...), db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    _check_admin(tg_id, db)
    recips = _pick_recipients(db)
    return {"count": len(recips)}

@router.post("/start")
def start(
    background_tasks: BackgroundTasks,
    init_data: str = Form(...),
    text: str = Form(""),
    photos: List[UploadFile] = File(default=[]),
    files:  List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    _check_admin(tg_id, db)

    # получатели
    recips = _pick_recipients(db)
    user_ids = [int(u.tg_id) for u in recips if str(u.tg_id).isdigit()]

    # прочитать вложения в память один раз
    album: List[tuple[str, bytes, str]] = []  # (name, data, 'photo'|'video'), макс 10
    docs:  List[tuple[str, bytes]] = []       # (name, data), макс 5

    # фото (image/*)
    for f in photos[:10]:
        if not (f.content_type or "").startswith("image/"): continue
        album.append((f.filename or "photo.jpg", f.file.read(), "photo"))

    # файлы/видео (до 5)
    for f in files[:5]:
        ct = f.content_type or ""
        data = f.file.read()
        if ct.startswith("video/"):
            if len(album) < 10:
                album.append((f.filename or "video.mp4", data, "video"))
        else:
            docs.append((f.filename or "file.bin", data))

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "total": len(user_ids), "processed": 0, "sent": 0, "fails": [], "done": False,
        "text": (text or "").strip(), "album": album, "docs": docs
    }

    async def _run(job_id: str, uids: List[int]):
        bot = Bot(settings.bot_token)
        try:
            for uid in uids:
                if JOBS.get(job_id, {}).get("cancel"): break
                try:
                    txt = JOBS[job_id]["text"]
                    if txt:
                        await bot.send_message(uid, txt, parse_mode="HTML", disable_web_page_preview=True)
                    if JOBS[job_id]["album"]:
                        media = []
                        for name, data, kind in JOBS[job_id]["album"][:10]:
                            if kind == "video":
                                media.append(InputMediaVideo(media=BufferedInputFile(data, filename=name)))
                            else:
                                media.append(InputMediaPhoto(media=BufferedInputFile(data, filename=name)))
                        await bot.send_media_group(uid, media)
                    for name, data in JOBS[job_id]["docs"][:5]:
                        await bot.send_document(uid, BufferedInputFile(data, filename=name))
                    JOBS[job_id]["sent"] += 1
                except Exception as e:
                    reason = _reason_from_exc(e)
                    try:
                        with SessionLocal() as s:
                            u = s.query(User).filter(User.tg_id == str(uid)).first()
                            if u:
                                JOBS[job_id]["fails"].append({
                                    "tg_id": str(uid), "name": u.name or "", "phone": u.phone or "",
                                    "reason": reason, "blocked": True
                                })
                                u.notifications = False
                                u.is_blocked = True
                                s.commit()
                            else:
                                JOBS[job_id]["fails"].append({
                                    "tg_id": str(uid), "name": "", "phone": "", "reason": reason, "blocked": True
                                })
                    except Exception:
                        JOBS[job_id]["fails"].append({
                            "tg_id": str(uid), "name": "", "phone": "", "reason": reason, "blocked": True
                        })
                finally:
                    JOBS[job_id]["processed"] += 1
                    await asyncio.sleep(0.2)
        finally:
            try: await bot.session.close()
            except: pass
            JOBS[job_id]["done"] = True

    background_tasks.add_task(_run, job_id, user_ids)
    return {"job_id": job_id, "total": len(user_ids)}

@router.get("/status")
def status(job_id: str):
    st = JOBS.get(job_id)
    if not st: raise HTTPException(404, "job not found")
    return {
        "total": st["total"],
        "processed": st["processed"],
        "sent": st["sent"],
        "failed_count": len(st["fails"]),
        "failed": st["fails"],
        "done": st["done"],
    }
