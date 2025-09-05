from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from ..config import settings
from ..db import get_db
from ..schemas import UserOut, RegisterFlat, UserCreate
from ..models import User
from ..security import validate_init_data, extract_tg_id

router = APIRouter(prefix="/api")

@router.post("/auth/validate")
def auth_validate(init_data: str = Body(..., embed=True)):
    ok = validate_init_data(init_data)
    if not ok:
        raise HTTPException(status_code=401, detail="invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id:
        raise HTTPException(status_code=401, detail="user missing")
    return {"ok": True, "tg_id": tg_id}

@router.get("/me", response_model=UserOut)
def me(init_data: str, db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(status_code=401, detail="invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    user = db.query(User).filter(User.tg_id == tg_id).first()
    if not user: raise HTTPException(status_code=404, detail="not registered")
    if settings.admin_id and user.tg_id == settings.admin_id and not user.is_admin:
        user.is_admin = True
        db.add(user); db.commit(); db.refresh(user)
    return user

@router.post("/register", response_model=UserOut)
def register(body: RegisterFlat = Body(...), db: Session = Depends(get_db)):
    ok = validate_init_data(body.init_data)
    if not ok: raise HTTPException(status_code=401, detail="invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    if not tg_id: raise HTTPException(status_code=401, detail="user missing")

    user = db.query(User).filter(User.tg_id == tg_id).first()
    if user:
        if settings.admin_id and user.tg_id == settings.admin_id and not user.is_admin:
            user.is_admin = True; db.commit(); db.refresh(user)
        return user

    user = User(
        tg_id=tg_id,
        name=body.name.strip(),
        city=body.city.strip(),
        phone=body.phone.strip(),
        role=body.role.strip(),
        notifications=True,
        is_admin=(settings.admin_id and tg_id == settings.admin_id),
        is_blocked=False
    )
    db.add(user); db.commit(); db.refresh(user)
    return user

@router.post("/me", response_model=UserOut)
def me_post(init_data: str = Body(..., embed=True), db: Session = Depends(get_db)):
    ok = validate_init_data(init_data)
    if not ok: raise HTTPException(status_code=401, detail="invalid initData")
    tg_id = extract_tg_id(ok.get("user"))
    user = db.query(User).filter(User.tg_id == tg_id).first()
    if not user: raise HTTPException(status_code=404, detail="not registered")
    return user
