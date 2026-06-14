#!/usr/bin/env bash
# Bring up Aegis with the edge (caddy + TLS on the public hostname).
# Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f ./.env ]; then set -a; . ./.env; set +a; fi

if [ -z "${AEGIS_PUBLIC_HOSTNAME:-}" ] || [ "$AEGIS_PUBLIC_HOSTNAME" = "localhost" ]; then
  echo "[edge-up] WARN: AEGIS_PUBLIC_HOSTNAME not set in .env -- caddy will fall back"
  echo "[edge-up]       to 'localhost' (no TLS). For your public host, add e.g."
  echo "[edge-up]       AEGIS_PUBLIC_HOSTNAME=aegis.<your-host>.sslip.io to .env"
fi

docker compose \
  -f docker-compose.yml \
  -f deploy-edge/docker-compose.edge.yml \
  up -d --build
