#!/usr/bin/env bash
# Aegis one-shot redeploy script for the GCP VM.
#
# Runs the full clean-deploy sequence in a single command:
#
#   1. git pull             -- fetch any new commits from GitHub
#   2. cleanup stale state  -- remove orphan containers + the legacy
#                              `aegis` docker network so compose can
#                              rebuild on a clean slate
#   3. rebuild frontend     -- with --no-cache so Dockerfile changes
#                              (entrypoint COPY, lock-file fixes, etc.)
#                              actually execute, not get layer-cached
#   4. compose up           -- with --force-recreate so the running
#                              container is replaced by one from the
#                              fresh image (otherwise compose reuses
#                              the old container and you don't see
#                              the new Dockerfile take effect)
#   5. keycloak settings    -- apply the Aegis login theme + redirect URIs
#                              to already-initialized Keycloak databases
#   6. verify               -- check that the entrypoint script is in
#                              the image, that config.js was regenerated
#                              with the public URLs, and that the
#                              entrypoint log line appeared at startup
#
# Idempotent: safe to re-run any time. Data volumes (postgres,
# keycloak, mongo, vault, caddy data) are NOT touched.
#
# Usage (on the VM, as the deploy user):
#   sudo bash /opt/aegis/aegis_platform/deploy/gcp/redeploy.sh
#
# Or, if the script has its exec bit:
#   sudo /opt/aegis/aegis_platform/deploy/gcp/redeploy.sh
#
# Exit codes:
#   0  success, site should be reachable at https://$DOMAIN
#   1  git pull failed (network or auth)
#   2  cleanup failed
#   3  frontend build failed
#   4  Keycloak settings or verification failed

set -euo pipefail

# ============================================================
# Style helpers
# ============================================================
say()  { printf "\n\033[1;34m==>\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m  ✓\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m  ⚠\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m  ✗\033[0m %s\n" "$*" >&2; }

# ============================================================
# Constants — match the existing deploy layout
# ============================================================
INSTALL_DIR="/opt/aegis/aegis_platform"
ENV_FILE="/etc/aegis/env"
PROJECT_NAME="aegis_platform"
COMPOSE_FLAGS=(
    --env-file "$ENV_FILE"
    -f docker-compose.yml
    -f deploy/gcp/docker-compose.production.yml
)

# ============================================================
# Pre-flight
# ============================================================
say "Pre-flight"
[ "$(id -u)" = "0" ] || { fail "Must run as root (use sudo)"; exit 1; }
[ -d "$INSTALL_DIR/.git" ] || { fail "Not a git repo: $INSTALL_DIR"; exit 1; }
[ -f "$ENV_FILE" ]        || { fail "Missing env file: $ENV_FILE"; exit 1; }
command -v docker >/dev/null || { fail "docker not installed"; exit 1; }
ok "$INSTALL_DIR is a git repo"
ok "$ENV_FILE present"
ok "docker available"

cd "$INSTALL_DIR"

# Read DOMAIN for the final print-out
DOMAIN=$(grep '^DOMAIN=' "$ENV_FILE" | head -1 | cut -d= -f2 || echo "<unknown>")
ok "Target domain: $DOMAIN"

# ============================================================
# Step 1 — git pull
# ============================================================
say "Step 1/5  git pull"
BEFORE=$(git rev-parse HEAD)
if ! git pull --ff-only; then
    fail "git pull failed (network down? merge conflict? PAT expired?)"
    exit 1
fi
AFTER=$(git rev-parse HEAD)
if [ "$BEFORE" = "$AFTER" ]; then
    ok "Already up to date ($AFTER)"
else
    ok "Updated $BEFORE → $AFTER"
fi

# ============================================================
# Step 2 — cleanup stale docker state
# ============================================================
say "Step 2/5  Cleanup stale containers + networks"
systemctl stop aegis.service 2>/dev/null || true

# Force-remove all aegis-* containers so they release any network holds
LIVE=$(docker ps -aq --filter "name=aegis" || true)
if [ -n "$LIVE" ]; then
    echo "$LIVE" | xargs docker rm -f >/dev/null
    ok "Removed $(echo "$LIVE" | wc -l) aegis container(s)"
else
    ok "No aegis containers to remove"
fi

# Remove the legacy `aegis` network if it's still around
if docker network inspect aegis >/dev/null 2>&1; then
    docker network rm aegis >/dev/null
    ok "Removed orphan 'aegis' network"
else
    ok "No orphan 'aegis' network"
fi

# Prune any other dangling networks
docker network prune -f >/dev/null
ok "Pruned dangling networks"

# ============================================================
# Step 3 — rebuild frontend image (no cache)
# ============================================================
say "Step 3/5  Rebuild frontend image (no cache; ~60-90s)"
if ! docker compose -p "$PROJECT_NAME" "${COMPOSE_FLAGS[@]}" build --no-cache frontend; then
    fail "Frontend image build failed"
    exit 3
fi
ok "Frontend image rebuilt"

# ============================================================
# Step 4 — bring the whole stack up
# ============================================================
say "Step 4/5  docker compose up (build + start every service)"
if ! docker compose -p "$PROJECT_NAME" "${COMPOSE_FLAGS[@]}" up -d --build; then
    fail "docker compose up failed"
    exit 3
fi
ok "All services started"

# Enable + start the systemd unit so future boots auto-start the stack
systemctl enable aegis.service >/dev/null 2>&1 || true
systemctl start aegis.service 2>/dev/null || true
ok "systemd unit enabled + started"

# ============================================================
# Step 5 — apply live Keycloak theme + redirect settings
# ============================================================
say "Step 5/6  Apply Keycloak hosted login theme + redirects"
if ! bash deploy/keycloak/apply-aegis-theme.sh; then
    fail "Keycloak hosted login theme / redirect update failed"
    exit 4
fi
ok "Keycloak realm uses Aegis login theme"

# ============================================================
# Step 6 — verify the three critical things
# ============================================================
say "Step 6/6  Verify entrypoint + config.js + entrypoint log"

# Wait a moment for the frontend container to fully start
sleep 3

FAIL=0

# 5a. Entrypoint script in image
if docker exec aegis_platform-frontend-1 \
        ls /docker-entrypoint.d/99-aegis-config.sh >/dev/null 2>&1; then
    ok "Entrypoint script present in image"
else
    fail "Entrypoint script MISSING in image"
    FAIL=1
fi

# 5b. config.js regenerated with real URLs (NOT localhost)
CFG=$(docker exec aegis_platform-frontend-1 \
        cat /usr/share/nginx/html/config.js 2>/dev/null || echo "")
if echo "$CFG" | grep -q '"http://localhost'; then
    fail "config.js still has localhost defaults"
    echo "$CFG" | sed 's/^/      /'
    FAIL=1
elif echo "$CFG" | grep -q 'KEYCLOAK_URL'; then
    ok "config.js looks healthy:"
    echo "$CFG" | sed 's/^/      /'
else
    fail "config.js not found or empty"
    FAIL=1
fi

# 5c. Entrypoint log line confirms the script actually ran
if docker logs aegis_platform-frontend-1 2>&1 | grep -q "aegis-config: wrote"; then
    LINE=$(docker logs aegis_platform-frontend-1 2>&1 | grep "aegis-config: wrote" | tail -1)
    ok "Entrypoint script ran at startup:"
    printf "      %s\n" "$LINE"
else
    warn "Did not find 'aegis-config: wrote' in frontend logs (script may not have run)"
    FAIL=1
fi

# ============================================================
# Done
# ============================================================
echo
if [ "$FAIL" -ne 0 ]; then
    fail "Some verifications failed — see above. The container may still be reachable, but config.js is probably wrong."
    echo
    echo "Tail recent logs with:"
    echo "  sudo docker compose -p $PROJECT_NAME logs --tail=80 frontend"
    exit 4
fi

cat <<EOF

  ====================================================
  ✅  Aegis is up.

  Site:           https://${DOMAIN}
  Keycloak admin: https://${DOMAIN}/auth/admin

  Tester accounts (password = password):
    jane@acmecp.example     analyst
    kim@acmecp.example      lead
    pat@acmecp.example      tenant-admin
    priya@it.example        platform-admin

  Open in a NEW InPrivate window so the browser doesn't
  reuse a cached /config.js from a previous load.

  Next deploys: just re-run this script.
    sudo $0
  ====================================================
EOF
