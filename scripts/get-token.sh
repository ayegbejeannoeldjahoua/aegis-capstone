#!/usr/bin/env bash
set -euo pipefail
USER_NAME=${1:-jane}
ROLE=${2:-analyst}
TENANT=${3:-acme-corp}
PASSWORD=${PASSWORD:-password}
CLIENT_ID=${CLIENT_ID:-aegis-cli}
curl -fsS -X POST http://localhost:8081/realms/aegis/protocol/openid-connect/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode "grant_type=password" \
  --data-urlencode "client_id=$CLIENT_ID" \
  --data-urlencode "username=$USER_NAME" \
  --data-urlencode "password=$PASSWORD" | jq -r .access_token
