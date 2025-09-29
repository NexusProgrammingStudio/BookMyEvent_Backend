# mypy: ignore-errors
import enum
import json
from datetime import datetime
from typing import Generator, List, Optional

from pydantic import field_validator
from sqlalchemy.orm import sessionmaker
from sqlmodel import (
    Field,
    Relationship,
    Session,
    SQLModel,
    create_engine,
)

# ----------------------
# Database Engine
# ----------------------
DATABASE_URL = "sqlite:///../Bookmyevent_db.db"
engine = create_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=Session
)


# ----------------------
# User Table
# ----------------------
class UserRole(str, enum.Enum):
    ORGANIZER = "organizer"
    CUSTOMER = "customer"
    ADMIN = "admin"


class UserBase(SQLModel):
    name: str
    username: str = Field(index=True, unique=True)
    email: str = Field(index=True, unique=True)
    role: UserRole
    interests: str = Field(default="[]")
    # NEW: coordinates
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("interests", mode="before")
    def serialize_interests(cls, v):
        if isinstance(v, list):
            return json.dumps(v)
        elif isinstance(v, str):
            return v
        return "[]"

    def get_interests(self) -> List[str]:
        return json.loads(self.interests)

    @property
    def intrest_list(self) -> List[str]:
        """Return intrests as Python list."""
        return json.loads(self.interests or "[]")


class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    hashed_password: str

    # Relationships
    events: List["Event"] = Relationship(back_populates="organizer")
    bookings: List["Booking"] = Relationship(back_populates="customer")


# -----------------------------
# Event
# -----------------------------
class EventBase(SQLModel):
    title: str
    description: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    venue: str
    categories: str = Field(default="[]")
    # NEW: coordinates
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("categories", mode="before")
    def parse_categories(cls, v):
        if isinstance(v, list):
            return json.dumps(v)  # convert list -> JSON string when saving
        elif isinstance(v, str):
            return v  # already JSON string
        return "[]"

    def get_categories(self) -> List[str]:
        return json.loads(self.categories)

    @property
    def category_list(self) -> List[str]:
        """Return categories as Python list."""
        return json.loads(self.categories or "[]")


class Event(EventBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    organizer_id: int = Field(foreign_key="user.id")

    # Relationships
    organizer: User = Relationship(back_populates="events")
    tickets: List["Ticket"] = Relationship(back_populates="event")
    bookings: List["Booking"] = Relationship(back_populates="events")


# -----------------------------
# Ticket
# -----------------------------
class TicketBase(SQLModel):
    type: str  # "General", "VIP", etc.
    price: float
    quantity: int


class Ticket(TicketBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: Optional[int] = Field(foreign_key="event.id")

    # Relationships
    event: Event = Relationship(back_populates="tickets")
    bookings: List["Booking"] = Relationship(back_populates="ticket")


# -----------------------------
# Booking
# -----------------------------
class BookingBase(SQLModel):
    quantity: int
    booked_at: datetime = Field(default_factory=datetime.utcnow)


class Booking(BookingBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="user.id")
    ticket_id: Optional[int] = Field(foreign_key="ticket.id")
    event_id: Optional[int] = Field(foreign_key="event.id")

    # Relationships
    customer: User = Relationship(back_populates="bookings")
    ticket: Ticket = Relationship(back_populates="bookings")
    events: Event = Relationship(back_populates="bookings")


# ----------------------
# Initialize Database
# ----------------------
def init_db() -> None:
    SQLModel.metadata.create_all(engine)


# ----------------------
# Session Generator
# ----------------------
def get_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency for a database session.
    Automatically closes session after request.
    """
    with Session(engine) as session:
        yield session
