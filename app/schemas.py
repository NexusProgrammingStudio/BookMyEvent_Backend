from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from .database import UserRole


# ------------------- Users -------------------
class UserCreate(BaseModel):
    name: str
    username: str
    email: EmailStr
    password: str
    role: UserRole


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


# ------------------- Tickets -------------------
class TicketCreate(BaseModel):
    type: str
    price: float
    quantity: int


class TicketOut(BaseModel):
    id: int
    type: str
    price: float
    quantity: int
    event_id: int

    model_config = {"from_attributes": True}


# ------------------- Events -------------------
class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    venue: str
    start_time: datetime
    end_time: Optional[datetime] = None
    tickets: Optional[List[TicketCreate]] = Field(default_factory=list)


class EventOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    venue: str
    start_time: datetime
    end_time: Optional[datetime] = None
    organizer_id: int
    tickets: List[TicketOut] = []

    model_config = {"from_attributes": True}


# ------------------- Bookings -------------------
class BookingCreate(BaseModel):
    ticket_id: int
    quantity: int


class BookingOut(BaseModel):
    id: int
    user_id: int
    ticket_id: int
    quantity: int

    model_config = {"from_attributes": True}
