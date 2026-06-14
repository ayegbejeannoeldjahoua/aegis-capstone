#!/usr/bin/env bash
set -euo pipefail
TOKEN=$(./scripts/get-token.sh jane analyst acme-corp)
echo "== Missing token denial =="
curl -s -o /dev/stdout -w '\nHTTP %{http_code}\n' http://localhost:8080/v1/ask -H 'Content-Type: application/json' -d '{"prompt":"x"}' || true

echo "== Unknown/disallowed model denial =="
curl -s -o /dev/stdout -w '\nHTTP %{http_code}\n' http://localhost:8080/v1/ask \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"prompt":"x","model":"unknown/provider"}' || true

echo "== Untrusted tool output injected-action denial recorded in audit =="
curl -fsS http://localhost:8080/v1/ask \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"prompt":"Widget defects Q1","inject_tool_output":true}' | jq
curl -fsS "http://localhost:8080/v1/audit/last?limit=10" -H "Authorization: Bearer $TOKEN" | jq
