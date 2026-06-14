# Aegis GCP deployment — zero-local, Cloud Shell + Git

This deploys the whole Aegis stack to a single Compute Engine VM in
**northamerica-northeast1 (Montréal)**, fronted by Caddy with automatic
Let's Encrypt TLS, addressable at a free `nip.io` hostname tied to the
VM's public IP.

**Once the VM is up, nothing on your laptop or in Cloud Shell needs to
keep running.** Testers hit the URL directly and the VM does everything.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Compute Engine VM   e2-standard-2 (2 vCPU, 8 GB)                │
│  northamerica-northeast1-a   50 GB SSD                           │
│                                                                   │
│  cloud-init: docker + git + cloned repo                          │
│  systemd: aegis.service runs docker compose                      │
│                                                                   │
│        :443 Caddy ──► docker network ──► frontend / api / kc      │
│                                          postgres / redis / mongo │
│                                          vault / opa / otel       │
└──────────────────────────────────────────────────────────────────┘
                          ▲
              https://aegis-{IP-with-dashes}.nip.io
              (free, auto-generated; Let's Encrypt cert is real)
```

## What you need

| Need | Where to get it |
|---|---|
| GCP project with billing | https://console.cloud.google.com |
| A Git repo for the project (private OK) | GitHub free tier; or Cloud Source Repositories |
| Cloud Shell | https://shell.cloud.google.com — free, in your browser |
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys |

Your laptop is only used to push the source to Git. After that, you can
do everything from Cloud Shell in any browser.

---

## One-time setup (~10 min, done once)

### 1. Push the project to Git

From your local terminal, in the project folder:

```bash
cd /path/to/aegis_platform
git init -b main
git add .
git commit -m "Aegis capstone deployment"
git remote add origin https://github.com/<you>/aegis-capstone.git
git push -u origin main
```

(Use a private repo. The `.env.production` is in `.gitignore` and never
gets pushed — only the example file does.)

### 2. Enable billing + compute API on your GCP project

In Cloud Shell:

```bash
export AEGIS_GCP_PROJECT=your-project-id
gcloud config set project "$AEGIS_GCP_PROJECT"
gcloud services enable compute.googleapis.com
```

---

## First deploy (~20 min, mostly waiting)

All commands from **Cloud Shell** (https://shell.cloud.google.com):

```bash
# 1. Clone your repo into Cloud Shell
git clone https://github.com/<you>/aegis-capstone.git
cd aegis-capstone

# 2. Create the production env file from the example, fill in secrets
cp deploy/gcp/.env.production.example deploy/gcp/.env.production
nano deploy/gcp/.env.production
# - Set OPENAI_API_KEY to your real key
# - Set ACME_EMAIL to any address (Let's Encrypt registration)
# - Generate the random secrets:
#     openssl rand -hex 16   # AEGIS_ADMIN_TOKEN
#     openssl rand -hex 16   # AEGIS_LOCAL_MASTER_KEY
#     openssl rand -hex 16   # AEGIS_AUDIT_KEY
#     openssl rand -hex 16   # POSTGRES_PASSWORD
#     openssl rand -hex 24   # KEYCLOAK_ADMIN_PASSWORD
#     openssl rand -hex 16   # VAULT_TOKEN
# - DOMAIN stays blank — deploy.sh fills it in

# 3. Export the required env vars
export AEGIS_GCP_PROJECT=your-project-id
export AEGIS_REPO=https://github.com/<you>/aegis-capstone.git
export AEGIS_BRANCH=main    # optional

# 4. Run the deploy
./deploy/gcp/deploy.sh up
```

`deploy.sh up`:

1. Creates an e2-standard-2 VM with cloud-init as user-data.
   Cloud-init installs Docker, opens the firewall to 80/443, clones
   `$AEGIS_REPO`, and registers a systemd unit `aegis.service`.
2. Opens TCP 80 + 443 via a firewall rule.
3. Polls for bootstrap completion (~2-3 min).
4. Reads the VM's public IP, computes `aegis-XX-XX-XX-XX.nip.io`,
   patches that into your local `.env.production`.
5. Uploads the env file to `/etc/aegis/env` (chmod 600, root-owned).
6. SSHes in and starts `aegis.service`, which runs
   `docker compose -f docker-compose.yml -f deploy/gcp/docker-compose.production.yml up -d --build`.
   First build is 10-15 min (torch + spaCy + Presidio + sentence-transformers).
7. Prints the live URL.

When the api container is healthy, Caddy fetches a real Let's Encrypt
cert within ~60s. Open the URL.

---

## Tester accounts

The api's bootstrap step provisions the fixture users (jane, kim, pat,
priya, plus everyone else in the seed YAML) into Keycloak on startup.

To see / reset tester passwords from any browser:

```
https://aegis-XX-XX-XX-XX.nip.io/auth/admin
```

Sign in with `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` from your env
file. Under **Users**, you'll see every fixture user. Click **Credentials
→ Reset password** to set a known password per tester, then email each
tester one line:

> Aegis test environment: **https://aegis-XX-XX-XX-XX.nip.io**
> Sign in as **jane@acmecp.example** with password **XXXXXXXX**
> Try one of the scenarios in the Aegis Test Scenarios document.

The roles (analyst / lead / tenant-admin / platform-admin) are already
wired by the bootstrap, so each tester sees the right surface.

---

## After deploy: your laptop and Cloud Shell can both go away

The VM keeps running 24/7 with `restart: unless-stopped` on every
container and `aegis.service` set to auto-start on VM boot. Testers just
need the URL.

**The only times you come back to Cloud Shell are:**

| Goal | Command (from Cloud Shell, in the repo) |
|---|---|
| Push a code update (git pull on VM, rebuild) | `./deploy/gcp/deploy.sh update` |
| Tail api logs | `./deploy/gcp/deploy.sh logs` |
| Open SSH session | `./deploy/gcp/deploy.sh ssh` |
| Stop the stack but keep the VM | `./deploy/gcp/deploy.sh down` |
| Delete the VM permanently | `./deploy/gcp/deploy.sh destroy` |
| Print the URL | `./deploy/gcp/deploy.sh url` |

---

## Costs

About **$50/month** if always-on with no credits:

| Resource | Monthly |
|---|---|
| e2-standard-2 (2 vCPU, 8 GB) 24/7 | ~$50 |
| 50 GB pd-balanced | ~$5 |
| 1-10 GB egress | free → ~$1 |
| Static external IP (attached to running VM) | free |

With your student credits this is essentially free for the demo period.

---

## Troubleshooting

### "Failed to fetch" in the chat

1. Caddy may still be provisioning the cert. Wait ~60s after api is healthy.
2. Check api: `./deploy/gcp/deploy.sh logs`
3. Check Caddy: `./deploy/gcp/deploy.sh ssh` → `sudo docker logs aegis-caddy --tail=50`

### Keycloak says "We're sorry…"

The KC_HOSTNAME settings depend on `$DOMAIN` being correct. Verify on the VM:
```
./deploy/gcp/deploy.sh ssh
cat /etc/aegis/env | grep DOMAIN
sudo docker compose -p aegis exec keycloak env | grep KC_HOSTNAME
```

### First build OOM-killed

`e2-standard-2` is 8 GB and torch installation peaks around 6 GB. If the
build fails:
```
./deploy/gcp/deploy.sh ssh
sudo systemctl stop aegis.service
sudo dmesg | tail -20      # confirm OOM
exit
gcloud compute instances stop aegis-demo --zone=northamerica-northeast1-a
gcloud compute instances set-machine-type aegis-demo --machine-type=e2-standard-4 \
    --zone=northamerica-northeast1-a
gcloud compute instances start aegis-demo --zone=northamerica-northeast1-a
./deploy/gcp/deploy.sh ssh
sudo systemctl start aegis.service
```
(e2-standard-4 has 16 GB — overkill at steady state but safe for the build.)

### sentence-transformers / spaCy didn't bake into the api image

The chat still works on keyword retrieval as a fallback. To rebuild fresh:
```
./deploy/gcp/deploy.sh ssh
cd /opt/aegis/aegis_platform
sudo docker compose -f docker-compose.yml -f deploy/gcp/docker-compose.production.yml build --no-cache api
sudo systemctl restart aegis.service
```

---

## What's NOT in this deployment

- No auto-scaling — single VM
- No managed Postgres / Redis / Mongo — all in containers on the VM disk
- No CDN for the frontend — Caddy serves Vite directly
- No log shipping to Cloud Logging — logs are local on the VM
- No HA / failover

All are reasonable upgrades after the capstone — moving Postgres to
Cloud SQL, swapping Caddy for a managed load balancer, putting the api
on Cloud Run — but the architecture supports each migration in isolation.
