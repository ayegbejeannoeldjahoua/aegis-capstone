#!/usr/bin/env bash
set -euo pipefail
TOKEN=$(./scripts/get-token.sh jane analyst acme-corp)
curl -fsS http://localhost:8080/v1/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"What is known about widget defects in Q1?","skill_id":"summarise-with-memory"}' | jq
