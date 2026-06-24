"""
Celery app configuration for background task processing.
"""

from celery import Celery
from app.config import settings
from dotenv import load_dotenv
load_dotenv()

# Create Celery instance
celery_app = Celery(
    "ai_textbook_generator",
    broker=settings.REDIS_CONNECTION_URL,
    backend=settings.REDIS_CONNECTION_URL,
)

# Configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,       # 1 hour max per task
    result_expires=3600,        # auto-clean result keys after 1 h
    task_acks_late=True,        # ack only after task completes — safe retry on worker crash
    worker_prefetch_multiplier=1,   # one task per worker at a time — fair scheduling
    worker_max_tasks_per_child=10,  # recycle worker process after 10 tasks — prevent memory leaks
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])
