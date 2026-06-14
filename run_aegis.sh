#!/usr/bin/env bash
# Aegis AI Governance Platform — local orchestration.
#
# Brings up the full Aegis stack with the synthetic-data fixture loaded.
#
# Prereqs:
#   - Docker + docker compose v2 on the host
#   - Free ports: 5432, 6379, 8080, 8081, 8181, 8200, 8889, 16686, 4317, 4318, 27017, 5173
#
# Usage:
#   bash run_aegis.sh up         # start the stack and bootstrap the fixture
#   bash run_aegis.sh down       # stop the stack
#   bash run_aegis.sh logs       # tail api logs
#   bash run_aegis.sh reseed     # re-trigger bootstrap (idempotent)
#   bash run_aegis.sh status     # health summary
#   bash run_aegis.sh nuke       # NUKE everything incl. Postgres + Mongo volumes
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

ensure_env() {
    if [ ! -f .env ]; then
        echo "[init] creating .env from .env.example"
        cp .env.example .env
    fi
}

start() {
    ensure_env

    echo "==[1/4]== docker compose up -d"
    docker compose -p aegis up -d

    echo "==[2/4]== Waiting for the stack to be healthy"
    if [ -f scripts/wait-for-stack.sh ]; then
        bash scripts/wait-for-stack.sh
    else
        sleep 30
    fi

    echo "==[3/4]== Bootstrapping fixture (creates tenants, users, roles, values, memories)"
    AEGIS_ADMIN_TOKEN="${AEGIS_ADMIN_TOKEN:-change-me-admin-token}" \
        AEGIS_API_URL="${AEGIS_API_URL:-http://localhost:8080}" \
        bash scripts/bootstrap.sh

    echo
    echo "============================================================"
    echo "Aegis AI Governance Platform is up."
    echo "============================================================"
    echo "Frontend (login + chat + admin):  http://localhost:5173"
    echo "API:                               http://localhost:8080"
    echo "Keycloak admin:                    http://localhost:8081  (admin / admin_change_me)"
    echo "Jaeger traces:                     http://localhost:16686"
    echo
    echo "End-user login (any tenant, password 'password'):"
    echo "  jane@acmecp.example                  (analyst, Acme Corp Research)"
    echo "  ben@betago.example                   (analyst, Beta Holdings)"
    echo
    echo "Platform admins (2 per tenant — they see the admin console):"
    echo "  pat@acmecp.example  /  kim@acmecp.example"
    echo "  pat@betago.example  /  kim@betago.example"
    echo "  (one pair per tenant: acmecp, betago, gammac, finsvc, hrops, saleseu, engcore, legalco)"
    echo
}

down() {
    docker compose -p aegis down
}

logs() {
    docker compose -p aegis logs -f api
}

reseed() {
    AEGIS_ADMIN_TOKEN="${AEGIS_ADMIN_TOKEN:-change-me-admin-token}" \
        AEGIS_API_URL="${AEGIS_API_URL:-http://localhost:8080}" \
        bash scripts/bootstrap.sh
}

status() {
    echo "== Containers =="
    docker compose -p aegis ps
    echo
    echo "== API health =="
    curl -sf http://localhost:8080/health 2>/dev/null | head -1 || echo "API not reachable"
    echo
    echo "== Counts in Postgres =="
    docker compose -p aegis exec -T postgres psql -U aegis -d aegis -c "
SELECT 'tenants' AS what, count(*) FROM tenants
UNION ALL SELECT 'teams', count(*) FROM teams
UNION ALL SELECT 'roles', count(*) FROM roles
UNION ALL SELECT 'user_assignments', count(*) FROM user_assignments
UNION ALL SELECT 'memories', count(*) FROM memories
UNION ALL SELECT 'audit_events', count(*) FROM audit_events;
" 2>/dev/null || echo "(Postgres not reachable yet)"
}

nuke() {
    read -p "This DESTROYS all data (Postgres + Mongo + Keycloak users). Continue? [y/N] " a
    [ "$a" = "y" ] && docker compose -p aegis down -v
}

case "${1:-up}" in
    up)     start ;;
    down)   down ;;
    logs)   logs ;;
    reseed) reseed ;;
    status) status ;;
    nuke)   nuke ;;
    *)      echo "Usage: $0 [up|down|logs|reseed|status|nuke]"; exit 1 ;;
esac
