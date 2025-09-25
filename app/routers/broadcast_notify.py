# app/routers/broadcast_notify.py
from __future__ import annotations
import asyncio, time, uuid
from typing import Dict, Any, List, Tuple

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

MAX_PHOTOS = 10
MAX_VIDEOS = 5
MAX_DOCS = 5


# -------- helpers --------
def _check_admin(tg_id: str, db: Session):
    u = db.query(User).filter(User.tg_id == tg_id).first()
    if not u or not (u.is_admin or str(tg_id) == str(settings.admin_id)):
        raise HTTPException(status_code=403, detail="forbidden")


def _pick_recipients(db: Session, include_tg_id: str | None = None) -> List[User]:
    rows = (
        db.query(User)
        .filter(User.notifications == True, User.is_blocked == False)
        .order_by(User.created_at.asc())
        .all()
    )
    # гарантированно добавляем отправителя
    if include_tg_id:
        me = db.query(User).filter(User.tg_id == include_tg_id).first()
        if me and all(str(u.tg_id) != str(include_tg_id) for u in rows):
            rows.insert(0, me)
    return rows


async def _send_photos(bot: Bot, chat_id: int, photos: List[Tuple[str, bytes]]) -> None:
    if not photos:
        return
    chunks = [photos[i:i + MAX_PHOTOS] for i in range(0, len(photos), MAX_PHOTOS)]
    for chunk in chunks:
        if len(chunk) == 1:
            name, data = chunk[0]
            await bot.send_photo(chat_id, BufferedInputFile(data, filename=name))
        else:
            media = [InputMediaPhoto(media=BufferedInputFile(d, filename=n)) for n, d in chunk]
            try:
                await bot.send_media_group(chat_id, media)
            except Exception:
                # fallback — по одному
                for name, data in chunk:
                    try:
                        await bot.send_photo(chat_id, BufferedInputFile(data, filename=name))
                    except Exception:
                        pass
        await asyncio.sleep(0.15)


async def _send_videos(bot: Bot, chat_id: int, videos: List[Tuple[str, bytes]]) -> None:
    if not videos:
        return
    chunks = [videos[i:i + MAX_VIDEOS] for i in range(0, len(videos), MAX_VIDEOS)]
    for chunk in chunks:
        if len(chunk) == 1:
            name, data = chunk[0]
            await bot.send_video(chat_id, BufferedInputFile(data, filename=name))
        else:
            media = [InputMediaVideo(media=BufferedInputFile(d, filename=n)) for n, d in chunk]
            try:
                await bot.send_media_group(chat_id, media)
            except Exception:
                # fallback — по одному
                for name, data in chunk:
                    try:
                        await bot.send_video(chat_id, BufferedInputFile(data, filename=name))
                    except Exception:
                        pass
        await asyncio.sleep(0.2)


async def _send_docs(bot: Bot, chat_id: int, docs: List[Tuple[str, bytes]]) -> None:
    for name, data in docs[:MAX_DOCS]:
        try:
            await bot.send_document(chat_id, BufferedInputFile(data, filename=name))
        except Exception:
            pass
        await asyncio.sleep(0.1)


# -------- state --------
JOBS: Dict[str, Dict[str, Any]] = {}


# -------- preview --------
@router.post("/preview")
async def preview(
        init_data: str = Form(...),
        text: str = Form(""),
        photos: List[UploadFile] = File(default=[]),
        files: List[UploadFile] = File(default=[]),
        db: Session = Depends(get_db),
):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    _check_admin(tg_id, db)

    # разобрать вложения
    photos_bytes: List[Tuple[str, bytes]] = []
    videos_bytes: List[Tuple[str, bytes]] = []
    docs_bytes: List[Tuple[str, bytes]] = []

    # фото (только image/*)
    for f in photos[:MAX_PHOTOS]:
        if (f.content_type or "").startswith("image/"):
            photos_bytes.append((f.filename or "photo.jpg", await f.read()))

    # файлы: видео в отдельный список, остальные — документы
    for f in files[:MAX_VIDEOS + MAX_DOCS]:
        ct = f.content_type or ""
        data = await f.read()
        if ct.startswith("video/") and len(videos_bytes) < MAX_VIDEOS:
            videos_bytes.append((f.filename or "video.mp4", data))
        elif not ct.startswith("video/") and len(docs_bytes) < MAX_DOCS:
            docs_bytes.append((f.filename or "file.bin", data))

    bot = Bot(settings.bot_token)
    try:
        if (text or "").strip():
            await bot.send_message(int(tg_id), text, parse_mode="HTML", disable_web_page_preview=True)
        await _send_photos(bot, int(tg_id), photos_bytes)
        await _send_videos(bot, int(tg_id), videos_bytes)
        await _send_docs(bot, int(tg_id), docs_bytes)
    finally:
        try:
            await bot.session.close()
        except:
            pass

    return {"ok": True}


# -------- start --------
@router.get("/recipients")
def recipients(init_data: str = Query(...), db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    _check_admin(tg_id, db)
    recips = _pick_recipients(db, include_tg_id=tg_id)
    return {"count": len(recips)}


@router.post("/start")
def start(
        background_tasks: BackgroundTasks,
        init_data: str = Form(...),
        text: str = Form(""),
        photos: List[UploadFile] = File(default=[]),
        files: List[UploadFile] = File(default=[]),
        db: Session = Depends(get_db),
):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    _check_admin(tg_id, db)

    # получатели
    recips = _pick_recipients(db, include_tg_id=tg_id)
    user_ids = [int(u.tg_id) for u in recips if str(u.tg_id).isdigit()]

    # вложения в память
    photos_buf: List[Tuple[str, bytes]] = []
    videos_buf: List[Tuple[str, bytes]] = []
    docs_buf: List[Tuple[str, bytes]] = []

    for f in photos[:MAX_PHOTOS]:
        if (f.content_type or "").startswith("image/"):
            photos_buf.append((f.filename or "photo.jpg", f.file.read()))

    for f in files[:MAX_VIDEOS + MAX_DOCS]:
        ct = f.content_type or ""
        data = f.file.read()
        if ct.startswith("video/") and len(videos_buf) < MAX_VIDEOS:
            videos_buf.append((f.filename or "video.mp4", data))
        elif not ct.startswith("video/") and len(docs_buf) < MAX_DOCS:
            docs_buf.append((f.filename or "file.bin", data))

    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "total": len(user_ids), "processed": 0, "sent": 0, "fails": [], "done": False,
        "text": (text or "").strip(), "photos": photos_buf, "videos": videos_buf, "docs": docs_buf
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
                    await _send_photos(bot, uid, JOBS[job_id]["photos"])
                    await _send_videos(bot, uid, JOBS[job_id]["videos"])
                    await _send_docs(bot, uid, JOBS[job_id]["docs"])
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
                    await asyncio.sleep(0.25)
        finally:
            try:
                await bot.session.close()
            except:
                pass
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
