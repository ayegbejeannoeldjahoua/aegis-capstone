#!/usr/bin/env bash
# Cleanup any stale Docker network / container state on the VM that's
# left over from previous deploys with different project names or
# different `name:` directives. Safe to run any time — data volumes
# (postgres, mongo, keycloak, vault) are NOT touched.
#
# Usage (on the VM, as the deploy user):
#   sudo ./deploy/gcp/cleanup-stale-state.sh
#
# What this does, in order:
#   1. Stops the systemd unit so docker compose isn't fighting us
#   2. Stops + force-removes every container named `aegis*`
#   3. Removes the orphan `aegis` network (if present)
#   4. Prunes any other dangling networks created by failed compose runs
#   5. Restarts the systemd unit, which `docker compose up -d --build`s
#      the stack on the freshly auto-generated network
#
# When to run:
#   - After a `git pull` that touches docker-compose.yml or the
#     production overlay's networks block
#   - When `docker network ls` shows a duplicate `aegis` and
#     `aegis_platform_default`
#   - After an aborted `systemctl restart` that left containers half-up

set -euo pipefail

say()  { printf "\n\033[1;34m==>\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m  ✓\033[0m %s\n" "$*"; }

say "Stopping aegis.service"
sudo systemctl stop aegis.service 2>/dev/null || true
ok "Service stopped"

say "Removing all aegis-* containers"
LIVE=$(sudo docker ps -aq --filter "name=aegis" || true)
if [ -n "$LIVE" ]; then
    echo "$LIVE" | xargs sudo docker rm -f >/dev/null
    ok "Removed $(echo "$LIVE" | wc -l) container(s)"
else
    ok "No aegis containers to remove"
fi

say "Removing the orphan 'aegis' docker network"
if sudo docker network inspect aegis >/dev/null 2>&1; then
    sudo docker network rm aegis >/dev/null
    ok "Removed 'aegis' network"
else
    ok "No 'aegis' network present"
fi

say "Pruning other dangling networks"
sudo docker network prune -f >/dev/null
ok "Network state is clean"

say "Restarting aegis.service"
sudo systemctl start aegis.service
ok "Service started (docker compose up -d --build is running in the background)"
echo
echo "Tail the api boot with:"
echo "    sudo docker compose -p aegis_platform logs -f --tail=40 api"
echo
echo "Open the site at: https://\$(grep ^DOMAIN /etc/aegis/env | cut -d= -f2)"
