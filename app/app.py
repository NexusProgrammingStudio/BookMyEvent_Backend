from contextlib import asynccontextmanager
from typing import AsyncGenerator, List, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from .auth import (
    admin_required,
    authenticate_user,
    create_token,
    customer_required,
    decode_refresh_token,
    get_current_user,
    hash_password,
    organizer_required,
    verify_password,
)
from .crud import (
    create_booking,
    create_event,
    create_user,
    get_event,
    list_events,
    update_event,
)
from .database import Booking, Event, Ticket, User, UserRole, get_session, init_db
from .schemas import (
    BookingCreate,
    BookingOut,
    EventCreate,
    EventOut,
    TicketCreate,
    TicketOut,
    Token,
    UserCreate,
    UserLogin,
)
from .tasks import notify_event_update, send_booking_email


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup logic
    init_db()
    yield


app = FastAPI(lifespan=lifespan, title="BookMyEvent API", version="1.0.0")


# Register endpoint
@app.post("/register")
def register(user: UserCreate, session: Session = Depends(get_session)) -> str:
    # check if username/email already exists
    statement = select(User).where(
        (User.username == user.username) | (User.email == user.email)
    )
    existing_user = session.exec(statement).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")

    return create_user(session, user)


# Login endpoint
@app.post("/login", response_model=Token)
def login(user: UserLogin, session: Session = Depends(get_session)) -> dict:
    statement = select(User).where(User.username == user.username)
    db_user = session.exec(statement).first()

    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    token = create_token({"sub": db_user.username})
    return {
        "access_token": token["access_token"],
        "refresh_token": token["refresh_token"],
        "token_type": "bearer",
    }


@app.post("/refresh", response_model=Token)
def refresh_token(refresh_token: str) -> dict:
    user_id: str = decode_refresh_token(refresh_token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    token = create_token({"sub": user_id})
    return {
        "access_token": token["access_token"],
        "refresh_token": token["refresh_token"],
        "token_type": "bearer",
    }


# Swagger Login
@app.post("/auto_login", include_in_schema=False)
def login_swagger(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
) -> dict:
    user = authenticate_user(form_data.username, form_data.password, session)
    token = create_token({"sub": user.username})
    return {"access_token": token["access_token"], "token_type": "bearer"}


# ------------------- Events -------------------
@app.post("/events/", response_model=EventOut)
def create_event_endpoint(
    event_in: EventCreate,
    db: Session = Depends(get_session),
    user: User = Depends(organizer_required),
) -> Event:
    if user.id is None:
        raise HTTPException(status_code=400, detail="Organizer ID is missing")
    elif user.role == UserRole.ORGANIZER or user.role == UserRole.ADMIN:
        return create_event(db, user.id, event_in)
    else:
        raise HTTPException(status_code=403, detail="Not authorized")


@app.get("/events/", response_model=List[EventOut])
def list_events_endpoint(db: Session = Depends(get_session)) -> List[Event]:
    return list_events(db)


@app.get("/events/{event_id}", response_model=EventOut)
def get_event_endpoint(event_id: int, db: Session = Depends(get_session)) -> Event:
    event = get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.put("/events/{event_id}", response_model=EventOut)
def update_event_endpoint(
    event_id: int,
    event_in: EventCreate,
    db: Session = Depends(get_session),
    user: User = Depends(organizer_required),
) -> Event:
    event = get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.organizer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your event")
    updated_event = update_event(db, event, event_in)
    if not updated_event:
        raise HTTPException(status_code=404, detail="Event not found after update")

    # Notify booked users asynchronously
    for booking in getattr(updated_event, "_old_bookings", []):
        print("Notifying", booking.customer.email)  # type: ignore
        notify_event_update.delay(booking.customer.email, updated_event.title)  # type: ignore
    return updated_event


# ------------------- Tickets -------------------
@app.post("/tickets/", response_model=TicketOut)
def create_ticket_endpoint(
    ticket_in: TicketCreate,
    event_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(organizer_required),
) -> Ticket:
    event = get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.organizer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your event")

    statement = select(Ticket).where(
        Ticket.event_id == event_id, Ticket.type == ticket_in.type
    )
    existing_ticket = db.exec(statement).first()

    if existing_ticket:
        # Update existing ticket
        existing_ticket.price = ticket_in.price
        existing_ticket.quantity = ticket_in.quantity
        db.add(existing_ticket)
        db.commit()
        db.refresh(existing_ticket)
        return existing_ticket
    else:
        # Create a new ticket
        ticket = Ticket(
            event_id=event_id,
            type=ticket_in.type,
            price=ticket_in.price,
            quantity=ticket_in.quantity,
        )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@app.get("/tickets/all/", response_model=TicketOut)
def list_all_ticket_endpoint(
    event_id: Optional[int],
    db: Session = Depends(get_session),
    user: User = Depends(admin_required),
    skip: int = 0,
    limit: int = 100,
) -> List[Ticket]:
    if user.id is None:
        raise HTTPException(status_code=400, detail="Organizer or Admin ID is missing")
    if event_id:
        statement = select(Ticket).where(Ticket.event_id == event_id)
        return list(db.exec(statement).all())
    else:
        statement = select(Ticket).offset(skip).limit(limit)
        return list(db.exec(statement).all())


# ------------------- Bookings -------------------
@app.post("/bookings/", response_model=Booking)
def book_ticket_endpoint(
    booking_in: BookingCreate,
    db: Session = Depends(get_session),
    user: User = Depends(customer_required),
) -> Booking:
    if user.id is None:
        raise HTTPException(status_code=400, detail="Customer ID is missing")
    booking = create_booking(db, user.id, booking_in)

    # Trigger async email notification
    ticket = db.get(Ticket, booking.ticket_id)
    if not ticket or not ticket.event:
        raise HTTPException(
            status_code=404, detail="Ticket or associated event not found"
        )
    send_booking_email.delay(user.email, ticket.event.title)  # type: ignore

    return booking


@app.get("/booking/all/", response_model=List[Booking])
def list_all_booking_endpoint(
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100,
) -> List[Booking]:
    if user.id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    # if event_id:
    #     statement = select(Booking).where(Booking.ticket_id == event_id)
    #     return list(db.exec(statement).all())
    # else:send_booking_email.delay(user.email, ticket.event.title) # type: ignore

    statement = select(Booking).offset(skip).limit(limit)
    return list(db.exec(statement).all())
