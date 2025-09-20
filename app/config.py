from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseModel):
    bot_token: str = os.getenv("BOT_TOKEN", "")
    web_app_url: str = os.getenv("WEB_APP_URL", "http://localhost:8000")
    admin_username: str = os.getenv("ADMIN_USERNAME", "AIexandrMerkuIov")
    admin_id: str = os.getenv("ADMIN_ID", "").strip()
    sqlite_url: str = os.getenv("SQLITE_URL") or os.getenv("DATABASE_URL", "sqlite:///./app.db")
    inventory_api: str = os.getenv("INVENTORY_API", "https://admin.avaxmotors.ru/api/items.php")
    inventory_user_id: int = int(os.getenv("INVENTORY_USER_ID", "1") or "1")
    inventory_auth: str = os.getenv("INVENTORY_AUTH", "").strip()
    api_base: str = os.getenv("API_BASE", "https://admin.avaxmotors.ru")
    api_user_id: int = int(os.getenv("API_USER_ID", "1"))
    notify_chat_id_reserve: int = int(os.getenv("NOTIFY_CHAT_ID_RESERVE", "-1001811638529"))
    notify_thread_id_reserve: int = int(os.getenv("NOTIFY_THREAD_ID_RESERVE", "14"))  # 0 = без топика

settings = Settings()
