#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ ! -f .env.production ]; then
  echo ".env.production not found" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env.production
set +a

STAMP=$(date -u +%Y%m%d_%H%M%S)
BACKUP_DIR=${BACKUP_DIR:-backups/$STAMP}
mkdir -p "$BACKUP_DIR"

COMPOSE="docker compose --env-file .env.production -f docker-compose.prod.yml"

$COMPOSE exec -T -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql \
  mysqldump -uroot --single-transaction --routines --triggers "$MYSQL_DATABASE" \
  | gzip > "$BACKUP_DIR/mysql.sql.gz"

$COMPOSE exec -T worker tar -C /app -czf - outputs \
  > "$BACKUP_DIR/outputs.tar.gz"

echo "Backup created at $BACKUP_DIR"

