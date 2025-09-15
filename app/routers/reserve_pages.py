# app/routers/reserve_pages.py
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from time import time
from ..config import settings

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/admin/reserves")
def page_reserves(request: Request):
    return templates.TemplateResponse(
        "admin_reserves.html",
        {
            "request": request,
            "WEB_APP_URL": settings.web_app_url,
            "ADMIN_USERNAME": settings.admin_username,
            "ver": int(time()),              # ← версия для кэша
        },
        headers={"Cache-Control": "no-store"}  # ← страница не кэшируется
    )
