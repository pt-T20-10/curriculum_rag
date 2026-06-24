#!/bin/sh
set -eu

# Railway normally preserves the image entrypoint when overriding CMD. Keep a
# defensive fallback for runtimes that invoke this start script directly.
if [ "$(id -u)" = "0" ]; then
    exec /app/docker-entrypoint.sh "$0" "$@"
fi

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
