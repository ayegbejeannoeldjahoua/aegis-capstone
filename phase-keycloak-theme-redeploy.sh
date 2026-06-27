#!/usr/bin/env bash
set -euo pipefail

REPO="/mnt/c/Users/noelg/Documents/Other Documents/Industry project experimentation/ChatGPT_Enterprise AI agentic system/26062026/aegis"
PROJECT="${AEGIS_GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
ZONE="${AEGIS_GCP_ZONE:-us-central1-a}"
VM="${AEGIS_VM_NAME:-aegis-demo}"

echo "=================================================="
echo " PART 2: Redeploy Keycloak Figma login theme"
echo "=================================================="

cd "$REPO"

if [ -z "$PROJECT" ]; then
  echo "ERROR: GCP project not found."
  echo "Run:"
  echo "gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

echo "Project: $PROJECT"
echo "Zone:    $ZONE"
echo "VM:      $VM"

echo
echo "1) Redeploy on VM..."

gcloud compute ssh "$VM" \
  --zone "$ZONE" \
  --project "$PROJECT" \
  --command '
    set -euo pipefail
    cd /opt/aegis/aegis_platform

    echo "Set VM repo to aegis-capstone..."
    sudo git remote set-url origin https://github.com/ayegbejeannoeldjahoua/aegis-capstone.git

    echo "Fetch latest..."
    sudo git fetch origin main
    sudo git reset --hard origin/main

    echo "Redeploy..."
    sudo bash deploy/gcp/redeploy.sh

    echo "Container status..."
    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      ps
  '

echo
echo "2) Compute public URL..."

IP="$(gcloud compute instances describe "$VM" \
  --zone "$ZONE" \
  --project "$PROJECT" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"

URL="https://aegis-${IP//./-}.nip.io"

echo "URL=$URL"

echo
echo "3) Smoke test..."

curl -fsS "$URL" >/dev/null
echo "OK: frontend"

curl -fsS "$URL/config.js" >/dev/null
echo "OK: config.js"

curl -fsS "$URL/api/health" >/dev/null
echo "OK: api health"

curl -fsS "$URL/auth/realms/aegis/.well-known/openid-configuration" >/dev/null
echo "OK: keycloak discovery"

echo
echo "4) Verify Keycloak theme setting..."

gcloud compute ssh "$VM" \
  --zone "$ZONE" \
  --project "$PROJECT" \
  --command '
    set -euo pipefail
    cd /opt/aegis/aegis_platform

    sudo bash -lc "
      set -a
      . /etc/aegis/env
      set +a

      DC=\"docker compose --env-file /etc/aegis/env -f docker-compose.yml -f deploy/gcp/docker-compose.production.yml\"

      \$DC exec -T keycloak /opt/keycloak/bin/kcadm.sh config credentials \
        --server http://localhost:8080/auth \
        --realm master \
        --user \"\$KEYCLOAK_ADMIN\" \
        --password \"\$KEYCLOAK_ADMIN_PASSWORD\" >/dev/null

      echo \"Realm theme:\"
      \$DC exec -T keycloak /opt/keycloak/bin/kcadm.sh get realms/aegis --fields realm,loginTheme

      echo \"Client redirects:\"
      \$DC exec -T keycloak /opt/keycloak/bin/kcadm.sh get clients -r aegis -q clientId=aegis-cli --fields clientId,redirectUris,webOrigins
    "
  '

echo
echo "=================================================="
echo "PART 2 DONE"
echo "=================================================="
echo
echo "Open in a fresh private browser:"
echo "$URL"
echo
echo "Expected:"
echo "  1. No React login page."
echo "  2. Browser redirects directly to Keycloak."
echo "  3. Keycloak page is Figma/Aegis styled."
echo "  4. User enters credentials once."
echo "  5. User lands directly inside Aegis."
echo
echo "Test users:"
echo "  priya@it.example / password"
echo "  jane@acmecp.example / password"
echo "  kim@acmecp.example / password"
echo "  pat@acmecp.example / password"
