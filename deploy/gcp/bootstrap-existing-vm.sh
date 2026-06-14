#!/usr/bin/env bash
# One-shot bootstrap for an EXISTING GCP / Debian-or-Ubuntu VM.
#
# What this does, in order:
#   1. Installs Docker, docker compose plugin, git, jq, ufw, openssl
#   2. Opens the host firewall to 22/80/443
#   3. Clones the Aegis repo to /opt/aegis/aegis_platform
#      (asks once for your GitHub Personal Access Token)
#   4. Detects the VM's public IP and derives the nip.io domain
#   5. Asks for OPENAI_API_KEY and ACME_EMAIL  (the only two real prompts)
#   6. Auto-generates the six random secrets the platform needs
#   7. Writes /etc/aegis/env  (chmod 600, root-owned)
#   8. Runs docker compose -f docker-compose.yml -f deploy/gcp/docker-compose.production.yml
#      up -d --build  (first build takes 10-15 minutes; logs print live)
#
# What it does NOT do:
#   - Open the GCP VPC firewall (the VPC rule is project-level; see the
#     ONE gcloud command printed at the bottom — run it once in Cloud Shell)
#
# Re-runs are safe: idempotent. Skips already-done steps.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ayegbejeannoeldjahoua/aegis-capstone/main/deploy/gcp/bootstrap-existing-vm.sh -H "Authorization: token YOUR_PAT" | bash
#   (or download then `bash bootstrap-existing-vm.sh`)

set -euo pipefail
say()  { printf "\n\033[1;34m==>\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m  ✓\033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m  ✗\033[0m %s\n" "$*" >&2; exit 1; }
ask()  { local p="$1" v=""; read -rp "  $p " v; echo "$v"; }
asks() { local p="$1" v=""; read -rsp "  $p " v; echo "" >&2; echo "$v"; }

REPO_OWNER="ayegbejeannoeldjahoua"
REPO_NAME="aegis-capstone"
REPO_HTTPS="https://github.com/${REPO_OWNER}/${REPO_NAME}.git"
INSTALL_DIR="/opt/aegis/aegis_platform"
ENV_FILE="/etc/aegis/env"

# ============================================================
# Pre-flight
# ============================================================
say "Checking pre-flight"
[ "$(id -u)" = "0" ] && die "Don't run this as root. Re-run as the regular user; sudo is used per-command."
command -v sudo >/dev/null || die "sudo not available"
ok "User is $(whoami), sudo OK"

# ============================================================
# 1. Install Docker + git + tooling
# ============================================================
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "Docker + compose plugin already installed"
else
    say "Installing Docker + git + tooling"
    sudo apt-get update -qq
    sudo apt-get install -y ca-certificates curl git gnupg ufw jq openssl >/dev/null

    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/debian/gpg \
        -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -qq
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin >/dev/null
    sudo systemctl enable --now docker
    ok "Docker $(docker --version) installed"
fi

# Let the current user run docker without sudo on next login
sudo usermod -aG docker "$(whoami)" || true

# ============================================================
# 2. UFW (host firewall) — allow 22/80/443
# ============================================================
if sudo ufw status | grep -q "Status: active"; then
    ok "UFW already active"
else
    say "Configuring UFW (host firewall)"
    sudo ufw default deny incoming >/dev/null
    sudo ufw default allow outgoing >/dev/null
    sudo ufw allow 22/tcp >/dev/null
    sudo ufw allow 80/tcp >/dev/null
    sudo ufw allow 443/tcp >/dev/null
    sudo ufw --force enable >/dev/null
    ok "UFW active: 22, 80, 443 open"
fi

# ============================================================
# 3. Clone the repo
# ============================================================
if [ -d "$INSTALL_DIR/.git" ]; then
    ok "Repo already present at $INSTALL_DIR — pulling latest"
    cd "$INSTALL_DIR"
    git pull --ff-only || die "git pull failed in $INSTALL_DIR"
else
    say "Cloning $REPO_OWNER/$REPO_NAME"
    echo "  Paste your GitHub Personal Access Token (won't echo)."
    echo "  It needs only the 'repo' scope. Generate one at: https://github.com/settings/tokens"
    PAT=$(asks "PAT:")
    [ -n "$PAT" ] || die "Empty token"
    sudo mkdir -p /opt/aegis
    sudo chown "$(whoami):$(whoami)" /opt/aegis
    git clone "https://oauth2:${PAT}@github.com/${REPO_OWNER}/${REPO_NAME}.git" "$INSTALL_DIR"
    unset PAT
    ok "Cloned to $INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# ============================================================
# 4. Detect public IP and build domain
# ============================================================
say "Detecting public IP"
PUBLIC_IP=$(curl -fsS https://ifconfig.me 2>/dev/null || \
            curl -fsS https://checkip.amazonaws.com 2>/dev/null | tr -d '\n')
[ -n "$PUBLIC_IP" ] || die "Couldn't determine public IP"
DOMAIN="aegis-${PUBLIC_IP//./-}.nip.io"
ok "Public IP: $PUBLIC_IP"
ok "Domain:    $DOMAIN"

# ============================================================
# 5. Real prompts — only two things from you
# ============================================================
say "Two values needed from you (the only prompts)"
OPENAI_API_KEY=$(asks "OPENAI_API_KEY (sk-…):")
[ -n "$OPENAI_API_KEY" ] || die "OpenAI key is required for the chat"

ACME_EMAIL=$(ask "ACME_EMAIL (any address — Let's Encrypt registration):")
[ -n "$ACME_EMAIL" ] || die "Email is required"

# ============================================================
# 6. Generate the random secrets
# ============================================================
say "Generating random secrets"
gen() { openssl rand -hex 16; }
AEGIS_ADMIN_TOKEN=$(gen)
AEGIS_LOCAL_MASTER_KEY=$(gen)
AEGIS_AUDIT_KEY=$(gen)
POSTGRES_PASSWORD=$(gen)
KEYCLOAK_ADMIN_PASSWORD=$(openssl rand -hex 24)
VAULT_TOKEN=$(gen)
ok "Six secrets generated"

# ============================================================
# 7. Write /etc/aegis/env  (root-owned, chmod 600)
# ============================================================
say "Writing $ENV_FILE"
sudo mkdir -p /etc/aegis
sudo tee "$ENV_FILE" >/dev/null <<EOF
# Aegis production env — generated by bootstrap-existing-vm.sh
DOMAIN=$DOMAIN
ACME_EMAIL=$ACME_EMAIL

OPENAI_API_KEY=$OPENAI_API_KEY

AEGIS_ADMIN_TOKEN=$AEGIS_ADMIN_TOKEN
AEGIS_LOCAL_MASTER_KEY=$AEGIS_LOCAL_MASTER_KEY
AEGIS_AUDIT_KEY=$AEGIS_AUDIT_KEY
AEGIS_SKILL_SIGNING_KEY=
AEGIS_SKILL_PUBLIC_KEY=

POSTGRES_USER=aegis
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=aegis

KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=$KEYCLOAK_ADMIN_PASSWORD

VAULT_TOKEN=$VAULT_TOKEN
EOF
sudo chmod 600 "$ENV_FILE"
sudo chown root:root "$ENV_FILE"
ok "$ENV_FILE written (root:root, 600)"

# Save the credentials sheet in a place you can read
CREDS="/opt/aegis/credentials.txt"
sudo tee "$CREDS" >/dev/null <<EOF
Aegis production deployment — $(date)

Public URL: https://$DOMAIN
Keycloak admin: https://$DOMAIN/auth/admin
  username: admin
  password: $KEYCLOAK_ADMIN_PASSWORD

After 'docker compose up' finishes, sign into Keycloak admin to view + reset
tester passwords (jane, kim, pat, priya, etc.).

Ops override (X-Admin-Token header on /admin/*):
  AEGIS_ADMIN_TOKEN: $AEGIS_ADMIN_TOKEN

Audit/master keys (back these up before destroying the VM):
  AEGIS_LOCAL_MASTER_KEY: $AEGIS_LOCAL_MASTER_KEY
  AEGIS_AUDIT_KEY:        $AEGIS_AUDIT_KEY

Datastore creds:
  Postgres: aegis / $POSTGRES_PASSWORD
  Vault:    $VAULT_TOKEN
EOF
sudo chmod 600 "$CREDS"
sudo chown "$(whoami):$(whoami)" "$CREDS"
ok "Credentials saved to $CREDS (back this file up!)"

# ============================================================
# 8. Bring the stack up
# ============================================================
say "Starting the Aegis stack (first build = 10-15 min; logs streaming below)"
echo "  If your SSH session disconnects, the build keeps running."
echo "  Reconnect with this SSH tab and run: docker compose -p aegis logs -f api"
echo

# Sourcing the env file at run-time avoids leaking it into the env of other
# processes on the VM. sudo -E preserves DOMAIN/etc through to docker compose.
set +e
sudo env $(grep -v '^#' "$ENV_FILE" | xargs) \
    docker compose \
    -f docker-compose.yml \
    -f deploy/gcp/docker-compose.production.yml \
    up -d --build
RC=$?
set -e
[ "$RC" -eq 0 ] || die "docker compose up failed (rc=$RC) — check the output above"

# ============================================================
# Final report + one gcloud command for the VPC firewall
# ============================================================
say "Done — Aegis is starting"
echo
echo "  ===================================================="
echo "  URL:    https://$DOMAIN"
echo "  KC:     https://$DOMAIN/auth/admin"
echo "  Creds:  $CREDS  (chmod 600 — back this up)"
echo "  ===================================================="
echo
echo "  IMPORTANT — the VPC firewall must allow tcp:80/443 to this VM."
echo "  Run this ONCE from Cloud Shell (https://shell.cloud.google.com):"
echo
echo "    gcloud compute firewall-rules create aegis-allow-http \\"
echo "        --direction=INGRESS --action=ALLOW \\"
echo "        --rules=tcp:80,tcp:443 \\"
echo "        --target-tags=http-server,https-server \\"
echo "        --source-ranges=0.0.0.0/0 \\"
echo "        --description='Aegis: Caddy HTTP/HTTPS'"
echo
echo "    gcloud compute instances add-tags YOUR_VM_NAME \\"
echo "        --zone=YOUR_ZONE \\"
echo "        --tags=http-server,https-server"
echo
echo "  After that + ~30s of Caddy obtaining the TLS cert, open the URL."
echo
echo "  To follow api logs:"
echo "    sudo docker compose -p aegis logs -f api"
echo
