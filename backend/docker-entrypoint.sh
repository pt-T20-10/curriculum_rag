#!/bin/sh
set -eu

APP_USER="appuser"
APP_GROUP="appuser"
APP_UID="10001"

prepare_runtime_dir() {
    runtime_dir="$1"

    mkdir -p "$runtime_dir"

    # A freshly mounted Railway/Docker volume is commonly owned by root.
    # Recurse only on the first mismatched mount so normal restarts stay fast,
    # while restored files also become accessible to the application user.
    current_uid="$(stat -c '%u' "$runtime_dir")"
    if [ "$current_uid" != "$APP_UID" ]; then
        echo "Adjusting ownership of $runtime_dir for $APP_USER (UID $APP_UID)..." >&2
        chown -R "$APP_USER:$APP_GROUP" "$runtime_dir"
    fi

    chmod u+rwx "$runtime_dir"
}

if [ "$(id -u)" = "0" ]; then
    prepare_runtime_dir /app/outputs
    prepare_runtime_dir /app/logs
    prepare_runtime_dir /app/data/chroma_db

    exec gosu "$APP_USER:$APP_GROUP" "$@"
fi

# Keep the image compatible with platforms that enforce a non-root runtime
# user and provision writable volumes through fsGroup or an init container.
exec "$@"
