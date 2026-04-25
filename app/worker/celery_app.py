from celery import Celery
from app.config import settings

# The Celery app instance.
# - broker: Redis queue where FastAPI deposits tasks
# - backend: Redis store where task results/status are kept
celery_app = Celery(
    "order_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # How long task results are kept in Redis (1 hour)
    result_expires=3600,
)
