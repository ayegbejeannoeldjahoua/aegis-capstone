#!/usr/bin/env bash
set -euo pipefail
ADMIN_TOKEN=${AEGIS_ADMIN_TOKEN:-change-me-admin-token}
TOKEN=$(./scripts/get-token.sh jane analyst acme-corp)
echo "== Hash-chain verification (admin) =="
curl -fsS http://localhost:8080/v1/audit/verify -H "X-Admin-Token: ${ADMIN_TOKEN}" | jq
echo "== Recent events for caller's tenant (tenant-scoped) =="
curl -fsS http://localhost:8080/v1/audit/last -H "Authorization: Bearer $TOKEN" | jq
printf '\nOpen Jaeger: http://localhost:16686\n'
