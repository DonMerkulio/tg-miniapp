from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/admin/users")
def users_page(request: Request):
    return templates.TemplateResponse("admin_users.html", {"request": request})
