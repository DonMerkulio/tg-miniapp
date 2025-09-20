from pydantic import BaseModel, Field, conlist
from typing import List, Optional

class UserCreate(BaseModel):
    name: str
    city: str
    phone: str
    role: str

class RegisterFlat(UserCreate):
    init_data: str  # Telegram initData

class UserOut(BaseModel):
    name: str
    city: str
    phone: str
    role: str
    notifications: bool
    is_admin: bool
    is_blocked: bool
    class Config:
        from_attributes = True

class Product(BaseModel):
    id: int
    brand: str
    model: str
    year: str
    part: str
    price: float
    currency: str
    photos: List[str] = Field(default_factory=list)
    description: str = ""
    warehouse: Optional[str] = None
