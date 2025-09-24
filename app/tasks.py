from .celery_worker import celery_app


@celery_app.task
def send_booking_email(user_email: str, event_title: str) -> None:
    print(f"📧 Sending booking confirmation email to {user_email} for {event_title}")


@celery_app.task
def notify_event_update(user_email: str, event_title: str) -> None:
    print(f"📢 Notifying {user_email} about updates to {event_title}")
