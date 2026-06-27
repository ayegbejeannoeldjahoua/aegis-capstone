#!/usr/bin/env bash
# Apply live Keycloak settings that realm import will not update once the
# production database already exists. Idempotent and safe to run after every
# deploy; never prints admin credentials.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${AEGIS_ENV_FILE:-/etc/aegis/env}"
if [ ! -f "$ENV_FILE" ] && [ -f "$ROOT_DIR/.env" ]; then
  ENV_FILE="$ROOT_DIR/.env"
fi
[ -f "$ENV_FILE" ] || { echo "[keycloak-theme] missing env file: $ENV_FILE" >&2; exit 1; }

set -a
. "$ENV_FILE"
set +a

KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin_change_me}"
DOMAIN="${DOMAIN:-}"
PROJECT_NAME="${PROJECT_NAME:-aegis_platform}"
KC_SERVER="${KEYCLOAK_ADMIN_SERVER:-http://localhost:8080/auth}"

COMPOSE_FLAGS=(--env-file "$ENV_FILE" -f docker-compose.yml)
if [ "$ENV_FILE" = "/etc/aegis/env" ] && [ -f deploy/gcp/docker-compose.production.yml ]; then
  COMPOSE_FLAGS+=(-f deploy/gcp/docker-compose.production.yml)
fi

redirects=(
  "http://localhost:5173/*"
  "http://localhost:8080/*"
  "http://localhost:3000/*"
)
origins=(
  "http://localhost:5173"
  "http://localhost:8080"
  "+"
)
if [ -n "$DOMAIN" ]; then
  redirects=("https://${DOMAIN}/*" "https://${DOMAIN}" "${redirects[@]}")
  origins=("https://${DOMAIN}" "${origins[@]}")
fi

REDIRECT_JSON=$(printf '%s\n' "${redirects[@]}" | python3 -c 'import json,sys; print(json.dumps([x.strip() for x in sys.stdin if x.strip()]))')
ORIGIN_JSON=$(printf '%s\n' "${origins[@]}" | python3 -c 'import json,sys; print(json.dumps([x.strip() for x in sys.stdin if x.strip()]))')

echo "[keycloak-theme] applying login theme and redirect settings"
docker compose -p "$PROJECT_NAME" "${COMPOSE_FLAGS[@]}" exec -T \
  -e KEYCLOAK_ADMIN="$KEYCLOAK_ADMIN" \
  -e KEYCLOAK_ADMIN_PASSWORD="$KEYCLOAK_ADMIN_PASSWORD" \
  -e KC_SERVER="$KC_SERVER" \
  -e AEGIS_REDIRECT_URIS="$REDIRECT_JSON" \
  -e AEGIS_WEB_ORIGINS="$ORIGIN_JSON" \
  keycloak sh <<'EOS'
set -eu

for i in $(seq 1 60); do
  if /opt/keycloak/bin/kcadm.sh config credentials \
      --server "$KC_SERVER" \
      --realm master \
      --user "$KEYCLOAK_ADMIN" \
      --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null 2>&1; then
    break
  fi
  if [ "$i" = "60" ]; then
    echo "[keycloak-theme] Keycloak admin API did not become ready" >&2
    exit 1
  fi
  sleep 2
done

/opt/keycloak/bin/kcadm.sh update realms/aegis -s loginTheme=aegis >/dev/null

CID=$(/opt/keycloak/bin/kcadm.sh get clients \
  -r aegis \
  -q clientId=aegis-cli \
  --fields id \
  --format csv \
  --noquotes | tail -n 1)

if [ -z "$CID" ]; then
  echo "[keycloak-theme] aegis-cli client not found" >&2
  exit 1
fi

/opt/keycloak/bin/kcadm.sh update "clients/$CID" \
  -r aegis \
  -s "redirectUris=${AEGIS_REDIRECT_URIS}" \
  -s "webOrigins=${AEGIS_WEB_ORIGINS}" >/dev/null
EOS

echo "[keycloak-theme] OK"
