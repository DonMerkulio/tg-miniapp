from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from ..config import settings

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/admin/shipments")
def page_create(request: Request):
    return templates.TemplateResponse("admin_shipments_create.html", {
        "request": request, "WEB_APP_URL": settings.web_app_url, "ADMIN_USERNAME": settings.admin_username
    })


@router.get("/admin/shipments/active")
def page_active(request: Request):
    return templates.TemplateResponse("admin_shipments_active.html", {
        "request": request, "WEB_APP_URL": settings.web_app_url, "ADMIN_USERNAME": settings.admin_username
    })


@router.get("/admin/moves")
def page_moves_create(request: Request):
    return templates.TemplateResponse("admin_moves_create.html", {
        "request": request, "WEB_APP_URL": settings.web_app_url, "ADMIN_USERNAME": settings.admin_username
    })


@router.get("/admin/moves/active")
def page_moves_active(request: Request):
    return templates.TemplateResponse("admin_moves_active.html", {
        "request": request, "WEB_APP_URL": settings.web_app_url, "ADMIN_USERNAME": settings.admin_username
    })


@router.get("/admin/broadcast/prices")
def page_broadcast_prices(request: Request):
    return templates.TemplateResponse("admin_broadcast_prices.html", {
        "request": request, "WEB_APP_URL": settings.web_app_url, "ADMIN_USERNAME": settings.admin_username
    })


@router.get("/admin/broadcast/notify")
def page_broadcast_notify(request: Request):
    return templates.TemplateResponse("admin_broadcast_notify.html", {
        "request": request, "WEB_APP_URL": settings.web_app_url, "ADMIN_USERNAME": settings.admin_username
    })
