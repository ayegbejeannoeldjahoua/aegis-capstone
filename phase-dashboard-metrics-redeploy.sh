#!/usr/bin/env bash
set -euo pipefail

REPO="/mnt/c/Users/noelg/Documents/Other Documents/Industry project experimentation/ChatGPT_Enterprise AI agentic system/26062026/aegis"
PROJECT="${AEGIS_GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
ZONE="${AEGIS_GCP_ZONE:-us-central1-a}"
VM="${AEGIS_VM_NAME:-aegis-demo}"

cd "$REPO"

if [ -z "$PROJECT" ]; then
  echo "ERROR: GCP project not found."
  echo "Run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

echo "== 1) Redeploy VM =="
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

    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      ps
  '

echo "== 2) Compute URL =="
IP="$(gcloud compute instances describe "$VM" \
  --zone "$ZONE" \
  --project "$PROJECT" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"

URL="https://aegis-${IP//./-}.nip.io"
echo "URL=$URL"

echo "== 3) Smoke test =="
curl -fsS "$URL" >/dev/null && echo "OK frontend"
curl -fsS "$URL/config.js" >/dev/null && echo "OK config"
curl -fsS "$URL/api/health" && echo
curl -fsS "$URL/auth/realms/aegis/.well-known/openid-configuration" >/dev/null && echo "OK keycloak"

echo "== 4) Dashboard endpoint check =="
gcloud compute ssh "$VM" \
  --zone "$ZONE" \
  --project "$PROJECT" \
  --command '
    set -euo pipefail
    cd /opt/aegis/aegis_platform

    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      logs --tail=80 api
  '

echo
echo "DONE."
echo "Open in a fresh browser profile:"
echo "$URL"
echo
echo "Login as:"
echo "  priya@it.example / password"
echo
echo "Then open Console → Dashboard and verify:"
echo "  - executive cards"
echo "  - governance cards"
echo "  - latency section"
echo "  - FinOps summary"
echo "  - audit/trace summary"
echo "  - retrieval summary"
echo "  - system/load section"
echo "  - recent decisions"
