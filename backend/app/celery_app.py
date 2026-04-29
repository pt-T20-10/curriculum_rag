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
    broker=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0",
    backend=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0",
)

# Configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])