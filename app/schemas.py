from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from .database import Event, UserRole


# ------------------- Users -------------------
class UserCreate(BaseModel):
    name: str
    username: str
    email: EmailStr
    password: str
    role: UserRole
    interests: Optional[List[str]] = Field(default_factory=list)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


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
    event_id: Optional[int]

    model_config = {"from_attributes": True}


# ------------------- Events -------------------
class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    venue: str
    start_time: datetime
    end_time: Optional[datetime] = None
    tickets: Optional[List[TicketCreate]] = Field(default_factory=list)
    categories: Optional[List[str]] = Field(default_factory=list)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class EventOut(BaseModel):
    id: Optional[int]
    title: str
    description: Optional[str]
    venue: str
    start_time: datetime
    end_time: Optional[datetime] = None
    organizer_id: int
    tickets: Optional[List[TicketOut]] = []
    categories: List[str]
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_instance(cls, event: Event) -> "EventOut":
        return cls(
            id=event.id,
            title=event.title,
            description=event.description,
            organizer_id=event.organizer_id,
            venue=event.venue,
            start_time=event.start_time,
            end_time=event.end_time,
            categories=event.category_list,  # convert JSON string -> list
            latitude=event.latitude,
            longitude=event.longitude,
            tickets=[
                TicketOut(
                    id=t.id,
                    type=t.type,
                    price=t.price,
                    quantity=t.quantity,
                    event_id=event.id,
                )
                for t in getattr(event, "tickets", [])
            ],
        )


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
