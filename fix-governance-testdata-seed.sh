#!/usr/bin/env bash
set -euo pipefail

REPO="/mnt/c/Users/noelg/Documents/Other Documents/Industry project experimentation/ChatGPT_Enterprise AI agentic system/26062026/aegis"
PROJECT="${AEGIS_GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
ZONE="${AEGIS_GCP_ZONE:-us-central1-a}"
VM="${AEGIS_VM_NAME:-aegis-demo}"

cd "$REPO"

echo "== 1) Local repo =="
pwd
git remote -v

echo
echo "== 2) Check augmentation files exist locally =="

REQUIRED=(
  "configs/fixtures/governance_test_fixture.yaml"
  "scripts/seed-governance-test-data.py"
  "scripts/reset-governance-test-data.py"
  "scripts/generate-governance-traffic.py"
  "tests/test_augmented_fixtures.py"
  "docs/AUGMENTED_TEST_DATA.md"
  "docs/TESTING_PROCEDURE.md"
)

MISSING=0
for f in "${REQUIRED[@]}"; do
  if [ -f "$f" ]; then
    echo "OK: $f"
  else
    echo "MISSING: $f"
    MISSING=1
  fi
done

if [ "$MISSING" -eq 1 ]; then
  echo
  echo "STOP: The governance augmentation patch has not been applied to this local repo."
  echo "First get/apply the Codex ZIP:"
  echo "aegis-governance-test-data-augmentation-patch-2026-06-26.zip"
  exit 1
fi

echo
echo "== 3) Validate Python scripts =="
python3 -m py_compile \
  scripts/seed-governance-test-data.py \
  scripts/reset-governance-test-data.py \
  scripts/generate-governance-traffic.py

echo
echo "== 4) Commit/push if needed =="

chmod +x \
  scripts/seed-governance-test-data.py \
  scripts/reset-governance-test-data.py \
  scripts/generate-governance-traffic.py

git status --short

git add "${REQUIRED[@]}"

if git diff --cached --quiet; then
  echo "No staged changes. Files may already be committed."
else
  git commit -m "testdata: add governance demonstration dataset"
fi

git push origin main

echo
echo "== 5) Redeploy VM from latest GitHub commit =="

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

    sudo git remote set-url origin https://github.com/ayegbejeannoeldjahoua/aegis-capstone.git
    sudo git fetch origin main
    sudo git reset --hard origin/main

    echo "Check script exists on VM filesystem:"
    test -f scripts/seed-governance-test-data.py
    ls -l scripts/seed-governance-test-data.py

    sudo bash deploy/gcp/redeploy.sh

    echo "Check script exists inside API container:"
    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      exec -T api ls -l /app/scripts/seed-governance-test-data.py

    echo "Seed governance test data:"
    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      exec -T api python3 scripts/seed-governance-test-data.py --reset-label-first

    echo "Dry-run traffic generator:"
    sudo docker compose \
      --env-file /etc/aegis/env \
      -f docker-compose.yml \
      -f deploy/gcp/docker-compose.production.yml \
      exec -T api python3 scripts/generate-governance-traffic.py --turns 20 --label smoke --dry-run
  '

echo
echo "DONE: governance test data scripts are deployed and seed command completed."
