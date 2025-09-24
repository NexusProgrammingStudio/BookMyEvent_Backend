from typing import List

from fastapi import HTTPException
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from .auth import get_current_user, hash_password
from .database import Booking, Event, Ticket, User
from .schemas import BookingCreate, EventCreate, UserCreate


# Users
def create_user(db: Session, user_in: UserCreate) -> str:
    # check if username/email already exists
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
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return "User Registration Complete"


# Events
def create_event(db: Session, organizer_id: int, event_in: EventCreate) -> Event:

    # check if username/email already exists
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


def list_events(db: Session, skip: int = 0, limit: int = 100) -> List[Event]:
    statement = select(Event).offset(skip).limit(limit)
    return list(db.exec(statement).all())


def update_event(db: Session, event: Event, event_in: EventCreate) -> Event | None:
    # 1. Collect existing bookings before overwriting tickets
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

    # Update simple fields only; ticket management may be extended
    event.title = event_in.title
    event.description = event_in.description
    event.venue = event_in.venue
    event.start_time = event_in.start_time
    event.end_time = event_in.end_time
    # Replace ticket types for simplicity
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
    # 4. Re-fetch updated event with relationships
    updated_event = db.exec(
        select(Event)
        .options(
            selectinload(Event.tickets)  # type: ignore
            .selectinload(Ticket.bookings)  # type: ignore
            .selectinload(Booking.customer)  # type: ignore
        )
        .where(Event.id == event.id)
    ).first()

    # 5. Attach old bookings temporarily for notifications
    if not updated_event:
        return None
    updated_event._old_bookings = old_bookings
    return updated_event


# Booking business logic
def create_booking(db: Session, customer_id: int, booking_in: BookingCreate) -> Booking:
    # Fetch ticket
    statement = select(Ticket).where(Ticket.id == booking_in.ticket_id)
    ticket = db.exec(statement).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if booking_in.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")

    if ticket.quantity < booking_in.quantity:
        raise HTTPException(status_code=400, detail="Not enough tickets available")

    # Reduce ticket quantity
    ticket.quantity -= booking_in.quantity

    booking = Booking(
        customer_id=customer_id, ticket_id=ticket.id, quantity=booking_in.quantity
    )
    db.add(booking)
    db.add(ticket)  # update ticket quantity
    db.commit()
    db.refresh(booking)
    return booking
