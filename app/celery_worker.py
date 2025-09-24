# from tasks import celery as celery_app

# # Autodiscover tasks
# celery_app.autodiscover_tasks(["BookMyEvent_Backend"])

# # To run the worker: celery -A app.celery_worker.celery_app worker --loglevel=info


from celery import Celery

celery_app = Celery(
    "celery_worker",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
)

# # Autodiscover tasks
celery_app.autodiscover_tasks(["app.tasks"])

celery_app.conf.task_routes = {
    "tasks.*": {"queue": "default"},
}
