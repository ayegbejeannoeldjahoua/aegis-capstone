#!/usr/bin/env bash
# Aegis GCP one-shot deployment — Cloud Shell + Git workflow.
#
# Design: the VM gets the project source via `git clone` driven by cloud-init.
# The deploy host (your laptop OR Cloud Shell) only runs gcloud commands —
# nothing about the running stack depends on it after `up` finishes.
#
# Subcommands:
#   ./deploy.sh up       create VM, hand it the repo URL, start the stack
#   ./deploy.sh update   `git pull` + `docker compose up -d --build` on the VM
#   ./deploy.sh logs     tail api logs
#   ./deploy.sh ssh      open an SSH session
#   ./deploy.sh down     stop the stack (keeps the VM)
#   ./deploy.sh destroy  delete the VM (irreversible)
#   ./deploy.sh url      print the public URL

set -euo pipefail

# ============================================================
# Required env vars — set in your shell BEFORE running:
# ============================================================
#   AEGIS_GCP_PROJECT   GCP project id   (e.g. my-capstone-2026)
#   AEGIS_REPO          Git URL of the project, https or ssh
#                       (e.g. https://github.com/you/aegis-capstone.git)
#   AEGIS_BRANCH        optional, default 'main'
#   AEGIS_ENV_FILE      path to the populated .env.production
#                       (default: ./deploy/gcp/.env.production)
# ============================================================
PROJECT_ID="${AEGIS_GCP_PROJECT:-}"
REGION="${AEGIS_GCP_REGION:-northamerica-northeast1}"
ZONE="${AEGIS_GCP_ZONE:-northamerica-northeast1-a}"
VM_NAME="${AEGIS_VM_NAME:-aegis-demo}"
MACHINE_TYPE="${AEGIS_VM_TYPE:-e2-standard-2}"
DISK_SIZE_GB="${AEGIS_VM_DISK:-50}"
IMAGE_FAMILY="ubuntu-2204-lts"
IMAGE_PROJECT="ubuntu-os-cloud"
REPO_URL="${AEGIS_REPO:-}"
REPO_BRANCH="${AEGIS_BRANCH:-main}"
ENV_FILE_LOCAL="${AEGIS_ENV_FILE:-./deploy/gcp/.env.production}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================
# Helpers
# ============================================================
say() { printf "\033[1;34m==>\033[0m %s\n" "$*"; }
die() { printf "\033[1;31m!!\033[0m %s\n" "$*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || die "missing '$1' — install it and re-run"; }

require gcloud
[ -n "$PROJECT_ID" ] || die "AEGIS_GCP_PROJECT not set. Run: export AEGIS_GCP_PROJECT=<your-project>"

# ============================================================
# Subcommands
# ============================================================

cmd_up() {
    [ -n "$REPO_URL" ] || die "AEGIS_REPO not set. Run: export AEGIS_REPO=https://github.com/you/aegis-capstone.git"
    [ -f "$ENV_FILE_LOCAL" ] || die "Missing env file: $ENV_FILE_LOCAL — copy .env.production.example, fill in secrets."

    say "Provisioning VM $VM_NAME in $ZONE  (project: $PROJECT_ID)"
    say "Repo:  $REPO_URL  (branch: $REPO_BRANCH)"

    # 1. Create the VM with cloud-init as user-data + repo URL as metadata
    gcloud compute instances create "$VM_NAME" \
        --project="$PROJECT_ID" \
        --zone="$ZONE" \
        --machine-type="$MACHINE_TYPE" \
        --image-family="$IMAGE_FAMILY" \
        --image-project="$IMAGE_PROJECT" \
        --boot-disk-size="${DISK_SIZE_GB}GB" \
        --boot-disk-type=pd-balanced \
        --tags=http-server,https-server,aegis \
        --metadata-from-file=user-data="$SCRIPT_DIR/cloud-init.yaml" \
        --metadata="AEGIS_REPO=$REPO_URL,AEGIS_BRANCH=$REPO_BRANCH" \
        --description="Aegis governance platform (capstone demo)"

    # 2. Firewall (idempotent)
    gcloud compute firewall-rules create aegis-allow-http \
        --project="$PROJECT_ID" --direction=INGRESS --action=ALLOW \
        --rules=tcp:80,tcp:443 --target-tags=http-server,https-server \
        --source-ranges=0.0.0.0/0 \
        --description="Aegis: Caddy HTTP/HTTPS" 2>/dev/null || true

    # 3. Wait for cloud-init to finish (Docker installed + repo cloned)
    say "Waiting for VM bootstrap (~2-3 min: apt update, Docker install, git clone)"
    until gcloud compute ssh "$VM_NAME" --project="$PROJECT_ID" --zone="$ZONE" \
        --command='test -f /opt/aegis/.bootstrap.done && test -d /opt/aegis/aegis_platform' >/dev/null 2>&1; do
        printf "."
        sleep 15
    done
    echo

    # 4. Resolve public IP, compute nip.io domain, patch env file
    PUBLIC_IP=$(gcloud compute instances describe "$VM_NAME" \
        --project="$PROJECT_ID" --zone="$ZONE" \
        --format='value(networkInterfaces[0].accessConfigs[0].natIP)')
    DOMAIN="aegis-${PUBLIC_IP//./-}.nip.io"
    say "VM public IP: $PUBLIC_IP"
    say "Production domain: $DOMAIN"
    sed -i.bak "s|^DOMAIN=.*|DOMAIN=$DOMAIN|" "$ENV_FILE_LOCAL"

    # 5. Ship the env file to the VM (chmod 600, root-owned)
    say "Uploading env file"
    gcloud compute scp --project="$PROJECT_ID" --zone="$ZONE" \
        "$ENV_FILE_LOCAL" "$VM_NAME":/tmp/aegis.env
    gcloud compute ssh --project="$PROJECT_ID" --zone="$ZONE" "$VM_NAME" \
        --command='sudo install -m 600 -o root -g root /tmp/aegis.env /etc/aegis/env && rm /tmp/aegis.env'

    # 6. Start the systemd unit (it builds + brings the stack up)
    say "Starting Aegis stack (10-15 min on first build: torch + spaCy + Presidio + sentence-transformers)"
    gcloud compute ssh --project="$PROJECT_ID" --zone="$ZONE" "$VM_NAME" \
        --command='sudo systemctl start aegis.service'

    say "Stack startup initiated. Caddy will provision TLS within ~60s of api becoming healthy."
    cmd_url
}

cmd_update() {
    say "git pull on the VM, then rebuild + restart api/frontend"
    gcloud compute ssh --project="$PROJECT_ID" --zone="$ZONE" "$VM_NAME" --command='
        set -e
        cd /opt/aegis/aegis_platform && \
        sudo -u $USER git pull --ff-only && \
        sudo systemctl restart aegis.service'
}

cmd_logs() {
    gcloud compute ssh --project="$PROJECT_ID" --zone="$ZONE" "$VM_NAME" --command='
        cd /opt/aegis/aegis_platform && \
        sudo docker compose -f docker-compose.yml -f deploy/gcp/docker-compose.production.yml logs -f --tail=100 api'
}

cmd_ssh() { gcloud compute ssh --project="$PROJECT_ID" --zone="$ZONE" "$VM_NAME"; }

cmd_down() {
    gcloud compute ssh --project="$PROJECT_ID" --zone="$ZONE" "$VM_NAME" \
        --command='sudo systemctl stop aegis.service'
}

cmd_destroy() {
    read -p "Really delete the VM $VM_NAME and firewall rule? (yes/no) " a
    [ "$a" = "yes" ] || die "Aborted."
    gcloud compute instances delete "$VM_NAME" --project="$PROJECT_ID" --zone="$ZONE" --quiet
    gcloud compute firewall-rules delete aegis-allow-http --project="$PROJECT_ID" --quiet 2>/dev/null || true
}

cmd_url() {
    DOMAIN=$(grep '^DOMAIN=' "$ENV_FILE_LOCAL" 2>/dev/null | cut -d= -f2 || echo "")
    [ -n "$DOMAIN" ] || die "DOMAIN not set in $ENV_FILE_LOCAL — run './deploy.sh up' first"
    cat <<URL

  ====================================================
  Aegis is live at:  https://$DOMAIN
  Keycloak admin:   https://$DOMAIN/auth/admin
  ====================================================

  Tester accounts are pre-provisioned in Keycloak by the
  scripts/bootstrap.sh that runs at api startup.
  Open the Keycloak admin URL to see usernames and reset
  passwords for each tester.

URL
}

# ============================================================
# Dispatch
# ============================================================
case "${1:-}" in
    up)      cmd_up ;;
    update)  cmd_update ;;
    logs)    cmd_logs ;;
    ssh)     cmd_ssh ;;
    down)    cmd_down ;;
    destroy) cmd_destroy ;;
    url)     cmd_url ;;
    *)
        cat <<USAGE
Usage: $0 {up|update|logs|ssh|down|destroy|url}

  up       Provision the VM, clone the repo, start the stack (first deploy)
  update   git pull on the VM, rebuild api/frontend
  logs     Tail the api logs
  ssh      Open an SSH session to the VM
  down     Stop the stack (keeps the VM and its disks)
  destroy  Delete the VM. Irreversible.
  url      Print the public URL

Required environment:
  export AEGIS_GCP_PROJECT=your-project-id
  export AEGIS_REPO=https://github.com/you/aegis-capstone.git
  [optional] export AEGIS_BRANCH=main
  And: deploy/gcp/.env.production exists with real secrets filled in.

Cloud Shell quick start:
  1. Open https://shell.cloud.google.com
  2. git clone YOUR_REPO && cd aegis_platform
  3. cp deploy/gcp/.env.production.example deploy/gcp/.env.production
     (fill in secrets — use 'openssl rand -hex 16' for the random ones)
  4. export AEGIS_GCP_PROJECT=...; export AEGIS_REPO=...
  5. ./deploy/gcp/deploy.sh up
USAGE
        ;;
esac
