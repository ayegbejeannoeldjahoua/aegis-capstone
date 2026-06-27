#!/usr/bin/env bash
set -euo pipefail

echo "== 1) Check required governance scripts exist locally =="

test -f scripts/seed-governance-test-data.py
test -f scripts/reset-governance-test-data.py
test -f scripts/generate-governance-traffic.py

echo "OK: governance scripts exist."

echo
echo "== 2) Patch Dockerfile.api to copy scripts into API image =="

python3 - <<'PY'
from pathlib import Path

p = Path("Dockerfile.api")
text = p.read_text()

if "COPY scripts ./scripts" in text:
    print("Dockerfile.api already copies scripts.")
else:
    lines = text.splitlines()
    inserted = False
    out = []

    for line in lines:
        out.append(line)

        if line.strip() == "COPY src ./src":
            out.append("COPY scripts ./scripts")
            inserted = True

    if not inserted:
        # Safe fallback: insert before pip install if COPY src pattern is different.
        out = []
        for line in lines:
            if not inserted and "pip install" in line:
                out.append("COPY scripts ./scripts")
                inserted = True
            out.append(line)

    if not inserted:
        raise SystemExit("Could not find a safe insertion point in Dockerfile.api")

    p.write_text("\n".join(out) + "\n")
    print("Patched Dockerfile.api with: COPY scripts ./scripts")
PY

echo
echo "== 3) Validate Dockerfile patch =="
grep -n "COPY scripts ./scripts" Dockerfile.api

echo
echo "== 4) Commit and push =="
git status --short

git add Dockerfile.api scripts/seed-governance-test-data.py scripts/reset-governance-test-data.py scripts/generate-governance-traffic.py configs/fixtures/governance_test_fixture.yaml tests/test_augmented_fixtures.py docs/AUGMENTED_TEST_DATA.md docs/TESTING_PROCEDURE.md

if git diff --cached --quiet; then
  echo "No staged changes. Nothing to commit."
else
  git commit -m "build: include governance test scripts in api image"
fi

git push origin main

echo
echo "== 5) Redeploy VM and seed governance data =="

PROJECT="${AEGIS_GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
ZONE="${AEGIS_GCP_ZONE:-us-central1-a}"
VM="${AEGIS_VM_NAME:-aegis-demo}"

if [ -z "$PROJECT" ]; then
  echo "ERROR: GCP project not found."
  echo "Run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

gcloud compute ssh "$VM" \
  --zone "$ZONE" \
  --project "$PROJECT" \
  --command '
    set -euo pipefail
    cd /opt/aegis/aegis_platform

    echo "Fetch latest source..."
    sudo git remote set-url origin https://github.com/ayegbejeannoeldjahoua/aegis-capstone.git
    sudo git fetch origin main
    sudo git reset --hard origin/main

    echo "Verify Dockerfile contains COPY scripts..."
    grep -n "COPY scripts ./scripts" Dockerfile.api

    echo "Redeploy with rebuild..."
    sudo bash deploy/gcp/redeploy.sh

    echo "Check script exists inside API container..."
    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      exec -T api ls -l /app/scripts/seed-governance-test-data.py

    echo "Seed governance test data..."
    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      exec -T api python3 scripts/seed-governance-test-data.py --reset-label-first

    echo "Dry-run traffic generator..."
    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      exec -T api python3 scripts/generate-governance-traffic.py --turns 20 --label smoke --dry-run
  '

echo
echo "DONE: API image now includes scripts, and governance seed command completed."
