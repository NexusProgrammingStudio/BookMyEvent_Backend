# tests/test_booking.py
import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, select

from app import crud
from app import database as models
from app.app import app as FastApp
from app.database import SessionLocal, engine
from app.schemas import EventCreate, TicketCreate, UserCreate, UserRole

client = TestClient(FastApp)


@pytest.fixture(scope="module", autouse=True)
def prepare_db() -> Generator[any, None, None]:  # type: ignore
    # fresh schema
    SQLModel.metadata.drop_all(bind=engine)
    SQLModel.metadata.create_all(bind=engine)

    db = SessionLocal()

    # create organizer and customer
    org_in = UserCreate(
        name="Org",
        username="org",
        email="org@example.com",
        password=os.getenv("PASSWORD", "secret"),
        role=UserRole.ORGANIZER,
    )
    cust_in = UserCreate(
        name="Cust",
        username="cust",
        email="cust@example.com",
        password=os.getenv("PASSWORD", "secret"),
        role=UserRole.CUSTOMER,
    )
    crud.create_user(db, org_in)
    crud.create_user(db, cust_in)

    # create event with tickets
    ev_in = EventCreate(
        title="Test Event",
        description="Desc",
        venue="Venue",
        start_time=datetime.utcnow(),
        end_time=datetime.utcnow() + timedelta(hours=2),
        tickets=[
            TicketCreate(type="GA", price=10.0, quantity=5),
        ],
    )
    statement = select(models.User).where(models.User.email == "org@example.com")
    organizer = db.exec(statement).first()
    crud.create_event(db, organizer.id, ev_in)  # type: ignore

    db.close()
    yield
    SQLModel.metadata.drop_all(bind=engine)


def get_token(username: str, password: str) -> str:
    r = client.post("/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["access_token"]


def test_successful_booking_and_availability() -> None:
    token = get_token("cust", "secret")

    # fetch event and ticket id
    r = client.get("/events/")
    assert r.status_code == 200
    events = r.json()
    assert len(events) > 0
    event = events[0]
    ticket = event["tickets"][0]

    # book 2 tickets
    r2 = client.post(
        "/bookings/",
        json={"event_id": event["id"], "ticket_id": ticket["id"], "quantity": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200
    booking = r2.json()
    assert booking["quantity"] == 2

    # book 4 more (should fail because only 3 remain)
    r3 = client.post(
        "/bookings/",
        json={"event_id": event["id"], "ticket_id": ticket["id"], "quantity": 4},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r3.status_code == 400
    assert "Not enough tickets" in r3.json()["detail"]
