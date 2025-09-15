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

settings = Settings()
