#!/bin/sh
set -eu

# Railway normally preserves the image entrypoint when overriding CMD. Keep a
# defensive fallback for runtimes that invoke this start script directly.
if [ "$(id -u)" = "0" ]; then
    exec /app/docker-entrypoint.sh sh "$0" "$@"
fi

CELERY_POOL="${CELERY_POOL:-solo}"
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-1}"

echo "Starting Celery worker (${CELERY_POOL}, concurrency=${CELERY_CONCURRENCY})..."
celery -A app.celery_app.celery_app worker \
    --loglevel=INFO \
    --pool="${CELERY_POOL}" \
    --concurrency="${CELERY_CONCURRENCY}" &

echo "Starting FastAPI on port ${PORT:-8000}..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips="*"
