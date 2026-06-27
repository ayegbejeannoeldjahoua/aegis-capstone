#!/usr/bin/env bash
set -euo pipefail

PROJECT="${AEGIS_GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
ZONE="${AEGIS_GCP_ZONE:-us-central1-a}"
VM="${AEGIS_VM_NAME:-aegis-demo}"

test -n "$PROJECT"

echo "== Redeploy and seed governance test data =="

gcloud compute ssh "$VM" \
  --zone "$ZONE" \
  --project "$PROJECT" \
  --command '
    set -euo pipefail
    cd /opt/aegis/aegis_platform

    sudo git remote set-url origin https://github.com/ayegbejeannoeldjahoua/aegis-capstone.git
    sudo git fetch origin main
    sudo git reset --hard origin/main

    sudo bash deploy/gcp/redeploy.sh

    echo "== Seed augmented governance test data =="
    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      exec -T api python3 scripts/seed-governance-test-data.py --reset-label-first

    echo "== Dry-run traffic generator =="
    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      exec -T api python3 scripts/generate-governance-traffic.py --turns 20 --label smoke --dry-run

    echo "== Container status =="
    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      ps
  '

IP="$(gcloud compute instances describe "$VM" \
  --zone "$ZONE" \
  --project "$PROJECT" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"

URL="https://aegis-${IP//./-}.nip.io"

echo "== Smoke test =="
curl -fsS "$URL" >/dev/null && echo "OK frontend"
curl -fsS "$URL/config.js" >/dev/null && echo "OK config"
curl -fsS "$URL/api/health" && echo
curl -fsS "$URL/auth/realms/aegis/.well-known/openid-configuration" >/dev/null && echo "OK keycloak"

echo
echo "Open:"
echo "$URL"
