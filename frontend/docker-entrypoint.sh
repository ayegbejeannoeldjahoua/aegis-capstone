#!/bin/sh
# /docker-entrypoint.d/99-aegis-config.sh
#
# Regenerate /usr/share/nginx/html/config.js from env vars at every
# container start. Runs as part of nginx:1.27-alpine's stock
# /docker-entrypoint.d/*.sh boot flow, BEFORE nginx starts serving.
#
# Why this exists
# ---------------
# The React app reads window.AEGIS_CONFIG at page load to discover the
# API base URL and Keycloak issuer. The static /public/config.js shipped
# with the build has localhost:8080 / localhost:8081 defaults so vite
# dev mode works. In production we need the real public URLs (passed in
# via VITE_API_BASE, VITE_KEYCLOAK_URL, etc. from
# deploy/gcp/docker-compose.production.yml). This script overwrites
# config.js with those values at every container start.
#
# Compose env vars consumed:
#   VITE_API_BASE          ->  AEGIS_CONFIG.API_BASE
#   VITE_KEYCLOAK_URL      ->  AEGIS_CONFIG.KEYCLOAK_URL
#   VITE_KEYCLOAK_REALM    ->  AEGIS_CONFIG.REALM
#   VITE_KEYCLOAK_CLIENT   ->  AEGIS_CONFIG.CLIENT_ID

set -eu

OUT=/usr/share/nginx/html/config.js

# Defaults preserved from /public/config.js so a bare `docker run`
# without env vars still produces a parseable config.js.
API_BASE="${VITE_API_BASE:-http://localhost:8080}"
KEYCLOAK_URL="${VITE_KEYCLOAK_URL:-http://localhost:8081}"
REALM="${VITE_KEYCLOAK_REALM:-aegis}"
CLIENT_ID="${VITE_KEYCLOAK_CLIENT:-aegis-cli}"

cat > "$OUT" <<EOF
window.AEGIS_CONFIG = {
  API_BASE: "${API_BASE}",
  KEYCLOAK_URL: "${KEYCLOAK_URL}",
  REALM: "${REALM}",
  CLIENT_ID: "${CLIENT_ID}",
};
EOF

echo "aegis-config: wrote $OUT (API_BASE=$API_BASE KEYCLOAK_URL=$KEYCLOAK_URL REALM=$REALM CLIENT_ID=$CLIENT_ID)"
