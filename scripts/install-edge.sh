#!/usr/bin/env bash
# Aegis turn-key edge installer (v1.19.2).
#
# Run this once after extracting the zip on a fresh VM. Subsequent VM reboots
# bring Aegis back up automatically via:
#   1. systemd starts dockerd on boot (default on GCP / Ubuntu / Debian)
#   2. every Aegis container has `restart: unless-stopped` -> they all come back
#   3. caddy reads its persistent /data volume -> TLS cert is reused
#
# Re-run is safe; this script is idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "[install-edge] checking prerequisites..."
command -v docker >/dev/null 2>&1 || { echo "FAIL: docker not installed" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "FAIL: docker compose v2 not installed" >&2; exit 1; }

# Make sure dockerd starts on boot.
if command -v systemctl >/dev/null 2>&1; then
  if ! systemctl is-enabled docker >/dev/null 2>&1; then
    echo "[install-edge] enabling docker.service to start on boot..."
    sudo systemctl enable docker || true
  fi
  if ! systemctl is-active docker >/dev/null 2>&1; then
    sudo systemctl start docker || true
  fi
fi

# Pull in .env, ensure required overrides exist.
if [ ! -f "${ROOT}/.env" ]; then
  echo "FAIL: ${ROOT}/.env not found. Copy .env.example to .env and set at least"
  echo "      a model provider key + AEGIS_PUBLIC_HOSTNAME before re-running." >&2
  exit 1
fi
set -a; . "${ROOT}/.env"; set +a

if [ -z "${AEGIS_PUBLIC_HOSTNAME:-}" ]; then
  echo "FAIL: AEGIS_PUBLIC_HOSTNAME not set in .env." >&2
  echo "      Add a line like:" >&2
  echo "        AEGIS_PUBLIC_HOSTNAME=aegis.<your-host>.sslip.io" >&2
  echo "        OIDC_PUBLIC_ISSUER=https://\${AEGIS_PUBLIC_HOSTNAME}/realms/aegis" >&2
  echo "        AEGIS_CORS_ORIGINS=https://\${AEGIS_PUBLIC_HOSTNAME}" >&2
  exit 1
fi
echo "[install-edge] public hostname: ${AEGIS_PUBLIC_HOSTNAME}"

# Bring up the stack with the edge overlay.
echo "[install-edge] building + starting services..."
"${ROOT}/scripts/edge-up.sh"

# Wait for the stack.
if [ -x "${ROOT}/scripts/wait-for-stack.sh" ]; then
  echo "[install-edge] waiting for stack health..."
  "${ROOT}/scripts/wait-for-stack.sh"
fi

# Seed fixtures.
echo "[install-edge] running bootstrap..."
"${ROOT}/scripts/bootstrap.sh"

# Configure Keycloak so the aegis-cli client accepts redirects from the
# public hostname (otherwise login fails with "Invalid parameter: redirect_uri").
if [ -x "${ROOT}/scripts/configure-edge-keycloak.sh" ]; then
  echo "[install-edge] configuring Keycloak redirect URIs..."
  "${ROOT}/scripts/configure-edge-keycloak.sh"
fi

echo
echo "[install-edge] DONE"
echo "[install-edge] open: https://${AEGIS_PUBLIC_HOSTNAME}"
echo "[install-edge] (Caddy will auto-issue a Let's Encrypt cert on first request -"
echo "[install-edge]  may take 10-30 s. If you see SSL_ERROR for ~30 s, that's why.)"
echo
echo "[install-edge] NOTE: open inbound TCP 80 and 443 in your cloud firewall."
echo "[install-edge]       GCP: gcloud compute firewall-rules create aegis-edge --allow tcp:80,tcp:443"
