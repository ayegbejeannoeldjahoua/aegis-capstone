#!/usr/bin/env bash
# backup.sh - full-fidelity backup of ALL persistent state for disaster recovery / migration.
# Captures both Postgres databases (the app DB AND Keycloak's user store incl. password
# hashes) plus the Mongo document corpora. Restore with scripts/restore.sh.
#   Usage:   bash scripts/backup.sh [output_dir]
#   Schedule (Windows): Task Scheduler -> wsl bash .../scripts/backup.sh
set -euo pipefail
TS="$(date +%Y%m%d-%H%M%S)"
OUT="${1:-backups/$TS}"
PGUSER="${POSTGRES_USER:-aegis}"
mkdir -p "$OUT"
echo "[1/2] Postgres (all databases: app + keycloak) -> $OUT/postgres-all.sql.gz"
docker compose exec -T postgres pg_dumpall -U "$PGUSER" | gzip > "$OUT/postgres-all.sql.gz"
echo "[2/2] Mongo (all document DBs) -> $OUT/mongo.archive.gz"
if docker compose exec -T mongo mongodump --archive 2>/dev/null | gzip > "$OUT/mongo.archive.gz"; then
  :
else
  echo "  (mongo unavailable or empty; skipped)"; rm -f "$OUT/mongo.archive.gz"
fi
echo "Backup complete -> $OUT"
