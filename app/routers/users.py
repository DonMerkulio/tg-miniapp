from fastapi import APIRouter, Depends, HTTPException, Query, Body, Path
from sqlalchemy.orm import Session
from sqlalchemy import or_
from ..db import get_db
from ..models import User
from ..security import validate_init_data, extract_tg_id

router = APIRouter(prefix="/api/users", tags=["users"])

def _check_admin(db: Session, init_data: str) -> str:
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(401, "invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id: raise HTTPException(401, "user missing")
    u = db.query(User).filter(User.tg_id == tg_id).first()
    if not u or not u.is_admin:
        raise HTTPException(403, "forbidden")
    return tg_id

def _to_user(u: User) -> dict:
    return {
        "id": u.id,
        "tg_id": u.tg_id,
        "name": u.name,
        "city": u.city,
        "phone": u.phone,
        "role": u.role,
        "notifications": u.notifications,
        "is_admin": u.is_admin,
        "is_blocked": u.is_blocked,
        "created_at": u.created_at.isoformat(),
    }

@router.get("")
def list_users(init_data: str, q: str | None = Query(None), db: Session = Depends(get_db)):
    _check_admin(db, init_data)
    q = (q or "").strip()
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.name.ilike(like), User.phone.ilike(like)))
    items = query.order_by(User.created_at.desc()).all()
    return {"items": [_to_user(u) for u in items]}

@router.get("/{uid}")
def get_user(uid: int = Path(...), init_data: str = Query(...), db: Session = Depends(get_db)):
    _check_admin(db, init_data)
    u = db.query(User).get(uid)
    if not u: raise HTTPException(404, "not found")
    return _to_user(u)

@router.patch("/{uid}")
def update_user(
    uid: int,
    init_data: str = Body(..., embed=True),
    payload: dict = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    _check_admin(db, init_data)
    u = db.query(User).get(uid)
    if not u: raise HTTPException(404, "not found")

    for k in ["name", "city", "phone", "role", "notifications", "is_admin", "is_blocked"]:
        if k in payload:
            setattr(u, k, payload[k])
    db.commit(); db.refresh(u)
    return {"ok": True, "item": _to_user(u)}
