#!/usr/bin/env bash
# Stop the Aegis stack (keeps named volumes; pass -v to wipe data).
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose \
  -f docker-compose.yml \
  -f deploy-edge/docker-compose.edge.yml \
  down "$@"
