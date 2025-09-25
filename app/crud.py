import json
from typing import List

from fastapi import HTTPException
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from .auth import get_current_user, hash_password
from .database import Booking, Event, Ticket, User
from .schemas import BookingCreate, EventCreate, UserCreate


# Users
def create_user(db: Session, user_in: UserCreate) -> str:
    statement = select(User).where(
        (User.username == user_in.username) | (User.email == user_in.email)
    )
    existing_user = db.exec(statement).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")

    db_user = User(
        name=user_in.username,
        username=user_in.username,
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        role=user_in.role,
        interests=json.dumps(user_in.interests or []),  # type: ignore
        latitude=user_in.latitude,
        longitude=user_in.longitude,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return "User Registration Complete"


#


# Events
def create_event(db: Session, organizer_id: int, event_in: EventCreate) -> Event:
    statement = select(Event).where(
        (Event.title == event_in.title) | (Event.venue == event_in.venue)
    )
    existing_event = db.exec(statement).first()
    if existing_event:
        raise HTTPException(status_code=400, detail="Event already exists")
    event = Event(
        title=event_in.title,
        description=event_in.description,
        venue=event_in.venue,
        start_time=event_in.start_time,
        end_time=event_in.end_time,
        organizer_id=organizer_id,
        categories=json.dumps(event_in.categories or []),
        latitude=event_in.latitude,
        longitude=event_in.longitude,
    )
    for t in event_in.tickets or []:
        ticket = Ticket(
            event_id=event.id,
            type=t.type,
            price=t.price,
            quantity=t.quantity,
        )
        event.tickets.append(ticket)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def get_event(db: Session, event_id: int) -> Event | None:
    get_events = select(Event).where((Event.id == event_id))
    return db.exec(get_events).first()


def list_events(db: Session, skip: int = 0, limit: int = 100) -> List[dict]:
    statement = select(Event).offset(skip).limit(limit)
    events = db.exec(statement).all()

    result = []
    for event in events:
        result.append(
            {
                "id": event.id,
                "title": event.title,
                "venue": event.venue,
                "description": event.description,
                "organizer_id": event.organizer_id,
                "start_time": event.start_time,
                "end_time": event.end_time,
                "categories": event.get_categories(),  # deserialize JSON string
                "latitude": event.latitude,
                "longitude": event.longitude,
                "tickets": [
                    {
                        "id": t.id,
                        "type": t.type,
                        "price": t.price,
                        "quantity": t.quantity,
                        "event_id": event.id,
                    }
                    for t in event.tickets
                ],
            }
        )

    return result


def update_event(db: Session, event: Event, event_in: EventCreate) -> Event | None:
    existing_event = db.exec(
        select(Event)
        .options(
            selectinload(Event.tickets)  # type: ignore
            .selectinload(Ticket.bookings)  # type: ignore
            .selectinload(Booking.customer)  # type: ignore
        )
        .where(Event.id == event.id)
    ).first()
    old_bookings = []
    if existing_event:
        for ticket in existing_event.tickets:
            old_bookings.extend(ticket.bookings)

    event.title = event_in.title
    event.description = event_in.description
    event.venue = event_in.venue
    event.start_time = event_in.start_time
    event.end_time = event_in.end_time
    event.categories = json.dumps(event_in.categories or [])
    event.latitude = event_in.latitude
    event.longitude = event_in.longitude
    event.tickets.clear()
    for t in event_in.tickets or []:
        ticket = Ticket(
            event_id=event.id,
            type=t.type,
            price=t.price,
            quantity=t.quantity,
        )
        event.tickets.append(ticket)
    db.add(event)
    db.commit()
    db.refresh(event)
    updated_event = db.exec(
        select(Event)
        .options(
            selectinload(Event.tickets)  # type: ignore
            .selectinload(Ticket.bookings)  # type: ignore
            .selectinload(Booking.customer)  # type: ignore
        )
        .where(Event.id == event.id)
    ).first()
    if not updated_event:
        return None
    updated_event._old_bookings = old_bookings
    return updated_event


def create_booking(db: Session, customer_id: int, booking_in: BookingCreate) -> Booking:
    statement = select(Ticket).where(Ticket.id == booking_in.ticket_id)
    ticket = db.exec(statement).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if booking_in.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")

    if ticket.quantity < booking_in.quantity:
        raise HTTPException(status_code=400, detail="Not enough tickets available")

    ticket.quantity -= booking_in.quantity

    booking = Booking(
        customer_id=customer_id, ticket_id=ticket.id, quantity=booking_in.quantity
    )
    db.add(booking)
    db.add(ticket)
    db.commit()
    db.refresh(booking)
    return booking
