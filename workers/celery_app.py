from celery import Celery
from celery.schedules import crontab
import os

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

app = Celery(
    "workers",
    broker=RABBITMQ_URL,
    backend=REDIS_URL,
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_routes={
        "tasks.recalculate_ratings": {"queue": "ratings"},
        "tasks.notify_match": {"queue": "notifications"},
    },
    beat_schedule={
        "recalculate-ratings-every-30-min": {
            "task": "tasks.recalculate_ratings",
            "schedule": crontab(minute="*/30"),
            "options": {"queue": "ratings"},
        },
    },
)

# ← ВАЖНО: импортируем tasks ПОСЛЕ настройки app
# Иначе декораторы @app.task не отработают
import tasks  # noqa