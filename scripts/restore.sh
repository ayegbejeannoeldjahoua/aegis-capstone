#!/usr/bin/env bash
# restore.sh - restore a backup produced by scripts/backup.sh into a FRESH stack
# (run after `docker compose up -d` on empty volumes; do NOT bootstrap first).
#   Usage: bash scripts/restore.sh backups/<timestamp>
set -euo pipefail
DIR="${1:?usage: bash scripts/restore.sh backups/<timestamp>}"
PGUSER="${POSTGRES_USER:-aegis}"
[ -f "$DIR/postgres-all.sql.gz" ] || { echo "missing $DIR/postgres-all.sql.gz" >&2; exit 1; }
echo "[1/2] Restoring Postgres (app + keycloak) from $DIR/postgres-all.sql.gz ..."
gunzip -c "$DIR/postgres-all.sql.gz" | docker compose exec -T postgres psql -U "$PGUSER" -d postgres
if [ -f "$DIR/mongo.archive.gz" ]; then
  echo "[2/2] Restoring Mongo from $DIR/mongo.archive.gz ..."
  gunzip -c "$DIR/mongo.archive.gz" | docker compose exec -T mongo mongorestore --archive --drop 2>/dev/null || echo "  (mongo restore skipped)"
fi
echo "Restore complete. Restart the API so it picks up the restored state: docker compose restart api"
