#!/bin/sh
set -eu

echo "Starting Celery worker (solo, concurrency=1)..."
celery -A app.celery_app.celery_app worker \
    --loglevel=INFO \
    --pool=solo \
    --concurrency=1 &

echo "Starting FastAPI on port ${PORT:-8000}..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips="*"

