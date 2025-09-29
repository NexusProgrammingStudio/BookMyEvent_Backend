from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field

from .database import Event, User, UserRole


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


class UserOut(BaseModel):
    id: Optional[int]
    name: str
    username: str
    email: EmailStr
    role: UserRole
    interests: List[str]
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    events: Optional[List["EventOut"]] = []
    past_bookings: Optional[List["BookingOut"]] = []

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_instance(cls, user: User) -> "UserOut":
        return cls(
            id=user.id,
            name=user.name,
            username=user.username,
            email=user.email,
            role=user.role,
            interests=user.intrest_list,  # convert JSON string -> list
            latitude=user.latitude,
            longitude=user.longitude,
            events=[
                EventOut(
                    id=e.id,
                    title=e.title,
                    description=e.description,
                    venue=e.venue,
                    start_time=e.start_time,
                    end_time=e.end_time,
                    organizer_id=e.organizer_id,
                    categories=e.category_list,  # convert JSON string -> list
                    latitude=e.latitude,
                    longitude=e.longitude,
                    tickets=[
                        TicketOut(
                            id=t.id,
                            type=t.type,
                            price=t.price,
                            quantity=t.quantity,
                            event_id=e.id,
                        )
                        for t in getattr(e, "tickets", [])
                    ],
                )
                for e in getattr(user, "events", [])
            ],
            past_bookings=[
                BookingOut(
                    id=b.id,
                    user_id=b.customer_id,
                    ticket_id=b.ticket_id,
                    event_id=b.event_id,
                    quantity=b.quantity,
                    booked_at=b.booked_at,
                )
                for b in getattr(user, "bookings", [])
            ],  # type: ignore
        )


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
    event_id: int
    quantity: int
    booked_at: datetime

    model_config = {"from_attributes": True}
