from sqlalchemy import String, Integer, Boolean, DateTime, Text
from sqlalchemy.orm import mapped_column, Mapped
from datetime import datetime
from .db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tg_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    city: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32))
    notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Shipment(Base):
    __tablename__ = "shipments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    category: Mapped[str] = mapped_column(String(128))  # категория
    articles: Mapped[str] = mapped_column(Text)  # артикул(а) — строкой
    warehouse: Mapped[str] = mapped_column(String(16))  # "москва" | "озеро"
    carrier: Mapped[str] = mapped_column(String(128))  # транспортная компания
    city: Mapped[str] = mapped_column(String(128))  # город получения
    client_info: Mapped[str] = mapped_column(Text)  # инфо о клиенте
    prepay: Mapped[bool] = mapped_column(Boolean, default=False)  # по предоплате
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    track_no: Mapped[str] = mapped_column(String(128), default="")  # трек (опционален)
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False)  # отправлено
    created_by: Mapped[str] = mapped_column(String(32))  # tg_id создателя


class Move(Base):
    __tablename__ = "moves"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    part: Mapped[str] = mapped_column(String(128))  # Запчасть
    articles: Mapped[str] = mapped_column(Text)  # Артикул(а)
    from_wh: Mapped[str] = mapped_column(String(16))  # "москва" | "озеро"
    to_wh: Mapped[str] = mapped_column(String(16))  # "москва" | "озеро"

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(32))  # tg_id
