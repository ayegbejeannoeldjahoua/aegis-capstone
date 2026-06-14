#!/usr/bin/env bash
# Aegis bootstrap (v1.19.1): seeds tenants/teams/roles/values + Keycloak logins.
# Idempotent -- safe to re-run.
#
# Auto-sources ./.env so the host shell sees the same AEGIS_ADMIN_TOKEN the api
# container loads via `env_file: .env`. Without this, a custom admin token in
# .env caused the api to reject bootstrap with a bare 401.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [ -f "${ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${ROOT}/.env"
  set +a
fi

ADMIN_TOKEN="${AEGIS_ADMIN_TOKEN:-change-me-admin-token}"
API_URL="${AEGIS_API_URL:-http://localhost:8082}"

if [ "$ADMIN_TOKEN" = "change-me-admin-token" ]; then
  echo "[bootstrap] WARN: AEGIS_ADMIN_TOKEN is the default. If your .env sets a"
  echo "[bootstrap]       different value the api will reject this with 401."
fi

body=$(mktemp)
http_code=$(curl -sS -o "$body" -w '%{http_code}' \
  -X POST "${API_URL}/admin/bootstrap" \
  -H "X-Admin-Token: ${ADMIN_TOKEN}" || echo "000")

if [ "$http_code" != "200" ]; then
  echo "[bootstrap] FAIL: api returned HTTP ${http_code}" >&2
  echo "[bootstrap]       body:" >&2; cat "$body" >&2; echo >&2
  if [ "$http_code" = "401" ]; then
    echo "[bootstrap] HINT: AEGIS_ADMIN_TOKEN mismatch. This script sourced ./.env;" >&2
    echo "[bootstrap]       confirm the api was started against the SAME .env" >&2
    echo "[bootstrap]       (compose env_file: .env). Then re-run." >&2
  fi
  rm -f "$body"; exit 1
fi

if command -v jq >/dev/null 2>&1; then jq < "$body"; else cat "$body"; echo; fi
rm -f "$body"

if command -v vault >/dev/null 2>&1; then
  export VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
  export VAULT_TOKEN="${VAULT_TOKEN:-root-dev-token-change-me}"
  vault kv put secret/aegis/audit \
    value="${AEGIS_AUDIT_KEY:-dev-audit-key-change-me}" >/dev/null || true
fi

echo "[bootstrap] OK"
