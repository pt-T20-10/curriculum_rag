#!/bin/sh
set -eu

attempts="${RAILWAY_PREDEPLOY_ATTEMPTS:-30}"
sleep_seconds="${RAILWAY_PREDEPLOY_SLEEP_SECONDS:-5}"

run_with_retry() {
    label="$1"
    shift

    attempt=1
    while [ "$attempt" -le "$attempts" ]; do
        echo "Railway predeploy: ${label} (attempt ${attempt}/${attempts})..."
        if "$@"; then
            echo "Railway predeploy: ${label} completed."
            return 0
        fi

        if [ "$attempt" -eq "$attempts" ]; then
            echo "Railway predeploy: ${label} failed after ${attempts} attempts." >&2
            return 1
        fi

        echo "Railway predeploy: ${label} failed; retrying in ${sleep_seconds}s..."
        attempt=$((attempt + 1))
        sleep "$sleep_seconds"
    done
}

run_with_retry "database migration" alembic upgrade head
run_with_retry "admin bootstrap" python -m app.bootstrap_admin
