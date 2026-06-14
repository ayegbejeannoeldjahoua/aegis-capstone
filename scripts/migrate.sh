#!/usr/bin/env bash
# Apply forward-only SQL migrations.
#
# v1.23.1: runs the migrator INSIDE the api container so we do not depend on
# a host-side python (GCP Debian only ships python3), nor on DATABASE_URL
# being exported in the host shell. The api container already has psycopg
# plus the migrations dir plus the right DATABASE_URL from compose env_file.
#
# Comments deliberately avoid backticks (bash interpreted them as command
# substitution and tried to run python on some hosts).
#
# Usage:
#   ./scripts/migrate.sh                            apply all pending migrations
#   ./scripts/migrate.sh deploy/postgres/migrations apply from a custom path
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.yml"
[ -f deploy-edge/docker-compose.edge.yml ] && COMPOSE="${COMPOSE} -f deploy-edge/docker-compose.edge.yml"

# Make sure the api container is up; the migrator needs DB connectivity.
if ! $COMPOSE ps --status running api 2>/dev/null | grep -q api; then
  echo "[migrate] api container is not running -- bringing the stack up first..."
  $COMPOSE up -d api
fi

$COMPOSE exec -T api python3 -m aegis_fabric.migrate "${1:-}"
