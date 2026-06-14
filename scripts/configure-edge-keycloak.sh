#!/usr/bin/env bash
# Configure Keycloak's aegis-cli client to accept the public hostname as
# a valid redirect_uri + web origin. Reads AEGIS_PUBLIC_HOSTNAME from .env so
# changing the domain later = changing one line + re-running this script.
#
# Idempotent: re-running with the same hostname is a no-op; with a different
# hostname it replaces the production redirect entries while keeping the
# localhost dev entries in place.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
if [ -f "${ROOT}/.env" ]; then set -a; . "${ROOT}/.env"; set +a; fi

if [ -z "${AEGIS_PUBLIC_HOSTNAME:-}" ]; then
  echo "[configure-kc] AEGIS_PUBLIC_HOSTNAME not set; nothing to do" >&2
  exit 0
fi

KC_ADMIN="${KEYCLOAK_ADMIN:-admin}"
KC_PASS="${KEYCLOAK_ADMIN_PASSWORD:-admin_change_me}"
KC_BASE="${AEGIS_KC_ADMIN_BASE:-http://keycloak:8080}"

COMPOSE="docker compose -f docker-compose.yml -f deploy-edge/docker-compose.edge.yml"

echo "[configure-kc] public hostname: ${AEGIS_PUBLIC_HOSTNAME}"
echo "[configure-kc] requesting master-realm admin token..."
TOKEN=$($COMPOSE exec -T api curl -sS -X POST \
  -d "client_id=admin-cli" \
  -d "username=${KC_ADMIN}" \
  -d "password=${KC_PASS}" \
  -d "grant_type=password" \
  "${KC_BASE}/realms/master/protocol/openid-connect/token" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
  echo "[configure-kc] FAIL: could not obtain admin token" >&2; exit 1
fi

echo "[configure-kc] looking up aegis-cli client UUID..."
CID=$($COMPOSE exec -T api curl -sS \
  -H "Authorization: Bearer ${TOKEN}" \
  "${KC_BASE}/admin/realms/aegis/clients?clientId=aegis-cli" \
  | python3 -c "import sys,json;arr=json.load(sys.stdin);print(arr[0]['id'] if arr else '')")
if [ -z "$CID" ]; then
  echo "[configure-kc] FAIL: aegis-cli client not found in realm 'aegis'" >&2
  echo "[configure-kc]       has bootstrap.sh been run?" >&2
  exit 1
fi

BODY=$(python3 -c "
import json
h = '${AEGIS_PUBLIC_HOSTNAME}'
print(json.dumps({
    'redirectUris': [f'https://{h}/*', 'http://localhost:5173/*'],
    'webOrigins':   [f'https://{h}', 'http://localhost:5173', '+'],
}))
")

echo "[configure-kc] PUT clients/${CID:0:8}... with new redirect URIs"
$COMPOSE exec -T api curl -sS -X PUT \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${BODY}" \
  "${KC_BASE}/admin/realms/aegis/clients/${CID}" >/dev/null

echo "[configure-kc] OK -- aegis-cli now accepts https://${AEGIS_PUBLIC_HOSTNAME}/*"
