import json
import math
from datetime import datetime
from typing import List, Optional

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
from .database import Booking, Event, Ticket, User, UserRole, get_session
from .ingestion import recommend_events_for_user
from .schemas import (
    BookingCreate,
    EventCreate,
    EventOut,
    TicketCreate,
    TicketOut,
    Token,
    UserCreate,
    UserLogin,
    UserOut,
)
from .tasks import notify_event_update, send_booking_email

# @asynccontextmanager
# async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
#     init_db()
#     yield


# app = FastAPI(lifespan=lifespan, title="BookMyEvent API", version="1.0.0")
app = FastAPI(title="BookMyEvent API", version="1.0.0")


# Register endpoint
@app.post("/register")
def register(user: UserCreate, session: Session = Depends(get_session)) -> str:
    statement = select(User).where(
        (User.username == user.username) | (User.email == user.email)
    )
    existing_user = session.exec(statement).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")

    return create_user(session, user)


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


@app.post("/auto_login", include_in_schema=False)
def login_swagger(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
) -> dict:
    user = authenticate_user(form_data.username, form_data.password, session)
    token = create_token({"sub": user.username})
    return {"access_token": token["access_token"], "token_type": "bearer"}


@app.post("/me", response_model=UserOut)
def read_users_me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.from_orm_instance(current_user)


# ------------------- Events -------------------
@app.post("/events/", response_model=Event)
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
def list_events_endpoint(db: Session = Depends(get_session)) -> List[dict]:
    return list_events(db)


@app.get("/events/{event_id}", response_model=EventOut)
def get_event_endpoint(event_id: int, db: Session = Depends(get_session)) -> EventOut:
    event = get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventOut.from_orm_instance(event)


@app.put("/events/{event_id}", response_model=EventOut)
def update_event_endpoint(
    event_id: int,
    event_in: EventCreate,
    db: Session = Depends(get_session),
    user: User = Depends(organizer_required),
) -> EventOut:
    event = get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.organizer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your event")
    updated_event = update_event(db, event, event_in)
    if not updated_event:
        raise HTTPException(status_code=404, detail="Event not found after update")

    for booking in getattr(updated_event, "_old_bookings", []):
        notify_event_update.delay(booking.customer.email, updated_event.title)  # type: ignore
    return EventOut.from_orm_instance(updated_event)


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
        existing_ticket.price = ticket_in.price
        existing_ticket.quantity = ticket_in.quantity
        db.add(existing_ticket)
        db.commit()
        db.refresh(existing_ticket)
        return existing_ticket
    else:
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
    statement = select(Booking).offset(skip).limit(limit)
    return list(db.exec(statement).all())


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371  # km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


@app.get("/users/recommendations")
def get_recommendations(
    user: User = Depends(get_current_user), db: Session = Depends(get_session)
) -> dict:
    if not user:
        return {"error": "User not found"}

    user_coordinates = (
        (user.latitude, user.longitude) if user.latitude and user.longitude else None
    )
    user_interests = user.get_interests()

    # 1️⃣ Past bookings → collect event categories
    stmt = (
        select(Event.id)
        .join(Ticket, Ticket.event_id == Event.id)  # type: ignore
        .join(Booking, Booking.ticket_id == Ticket.id)  # type: ignore
        .where(Booking.customer_id == user.id)
        .distinct()
    )
    booked_event_ids = [row for row in db.exec(stmt).all() if row is not None]

    booked_categories: list[str] = []
    if booked_event_ids:
        rows = db.exec(select(Event.categories).where(Event.id.in_(booked_event_ids))).all()  # type: ignore
        for row in rows:
            if row[0]:
                try:
                    booked_categories.extend(json.loads(row[0]))
                except Exception:
                    pass
    booked_categories = list(set(booked_categories))  # unique categories

    # 2️⃣ Consider only upcoming events
    all_events = db.exec(
        select(Event).where(Event.start_time >= datetime.utcnow())
    ).all()

    if not all_events:
        return {"user_id": user.id, "msg": "No Events Found in Future."}

    recommendations = []
    for event in all_events:
        score = 0.0
        reasons = []
        event_coordinates = (
            (event.latitude, event.longitude)
            if event.latitude and event.longitude
            else None
        )
        event_categories = event.get_categories()

        # Past bookings match
        if booked_categories and event_categories:
            overlap = set(event_categories) & set(booked_categories)
            if overlap:
                score += 0.5
                reasons.append(f"Similar to your past bookings: {', '.join(overlap)}")
        # Location match (within 10 km)
        if user_coordinates and event_coordinates:
            dist = haversine(*user_coordinates, *event_coordinates)
            if dist <= 10:
                score += 0.3
                reasons.append(f"Near your location (~{int(dist)} km)")
        # Interests match
        if user_interests and event_categories:
            overlap = set(user_interests) & set(event_categories)

            if overlap:
                score += 0.4
                reasons.append(f"Matches your interest(s): {', '.join(overlap)}")

        if score > 0:
            recommendations.append(
                {
                    "event_id": event.id,
                    "title": event.title,
                    "categories": event_categories,
                    "reason": "; ".join(reasons),
                    "score": round(score, 2),
                }
            )
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    return {"user_id": user.id, "recommendations": recommendations[:10]}


@app.get("/users/ai/recommendations")
def get_ai_recommendations(
    user: User = Depends(get_current_user), db: Session = Depends(get_session)
) -> dict:
    if not user:
        return {"error": "User not found"}

    user_dict = UserOut.from_orm_instance(user).model_dump()
    bookings_text = []
    for b in user_dict.get("past_bookings", []):
        event = db.get(Event, b["event_id"])
        if event:
            event_dict = EventOut.from_orm_instance(event).model_dump()
            categories = ", ".join(event_dict.get("categories", []))
            bookings_text.append(
                {
                    "Event": event_dict.get("title"),
                    "Categories": categories,
                    "Venue": event_dict.get("venue"),
                }
            )
    user_dict["past_bookings_text"] = bookings_text
    recommendations = recommend_events_for_user(
        user_doc=user_dict, top_k=5, max_distance_km=50
    )
    return {"user_id": user.id, "recommendations": recommendations}
