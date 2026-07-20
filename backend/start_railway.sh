#!/bin/sh
set -eu

# Railway normally preserves the image entrypoint when overriding CMD. Keep a
# defensive fallback for runtimes that invoke this start script directly.
if [ "$(id -u)" = "0" ]; then
    exec /app/docker-entrypoint.sh sh "$0" "$@"
fi

echo "Starting FastAPI with in-process textbook task runner on port ${PORT:-8000}..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips="*"
