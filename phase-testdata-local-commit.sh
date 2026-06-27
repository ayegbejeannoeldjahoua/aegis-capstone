#!/usr/bin/env bash
set -euo pipefail

REPO="/mnt/c/Users/noelg/Documents/Other Documents/Industry project experimentation/ChatGPT_Enterprise AI agentic system/26062026/aegis"
PATCH_ZIP="/mnt/c/Users/noelg/Documents/Other Documents/Industry project experimentation/ChatGPT_Enterprise AI agentic system/26062026/aegis-governance-test-data-augmentation-patch-2026-06-26.zip"
BRANCH="main"
COMMIT_MSG="testdata: add governance demonstration dataset"

cd "$REPO"

echo "== Check patch ZIP =="
test -f "$PATCH_ZIP"

echo "== Clean generated files =="
rm -rf frontend/node_modules frontend/dist node_modules dist .pytest_cache .ruff_cache
git restore frontend/package-lock.json package-lock.json 2>/dev/null || true

echo "== Backup repo =="
cd ..
zip -qr "aegis-PRE-governance-testdata-$(date +%F-%H%M).zip" aegis
cd "$REPO"

echo "== Verify ZIP contents =="
python3 - "$PATCH_ZIP" <<'PY'
import sys, zipfile
from pathlib import PurePosixPath

zip_path = sys.argv[1]
required = {
    "PATCH_NOTES.md",
    "configs/fixtures/governance_test_fixture.yaml",
    "scripts/seed-governance-test-data.py",
    "scripts/reset-governance-test-data.py",
    "scripts/generate-governance-traffic.py",
    "tests/test_augmented_fixtures.py",
    "docs/AUGMENTED_TEST_DATA.md",
    "docs/TESTING_PROCEDURE.md",
}
forbidden = {"node_modules", "dist", ".git", ".env", ".ruff_cache", ".pytest_cache", "__pycache__"}

with zipfile.ZipFile(zip_path) as z:
    names = set(z.namelist())
    missing = required - names
    if missing:
        raise SystemExit(f"Missing required files: {sorted(missing)}")
    for name in names:
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts:
            raise SystemExit(f"Unsafe ZIP path: {name}")
        if any(part in forbidden for part in p.parts):
            raise SystemExit(f"Forbidden path in ZIP: {name}")
print("ZIP OK")
PY

echo "== Apply patch =="
TMP="$(mktemp -d)"
unzip -q "$PATCH_ZIP" -d "$TMP"

FILES=(
  "configs/fixtures/governance_test_fixture.yaml"
  "scripts/seed-governance-test-data.py"
  "scripts/reset-governance-test-data.py"
  "scripts/generate-governance-traffic.py"
  "tests/test_augmented_fixtures.py"
  "docs/AUGMENTED_TEST_DATA.md"
  "docs/TESTING_PROCEDURE.md"
)

for f in "${FILES[@]}"; do
  mkdir -p "$(dirname "$f")"
  cp "$TMP/$f" "$f"
done

chmod +x scripts/seed-governance-test-data.py scripts/reset-governance-test-data.py scripts/generate-governance-traffic.py

echo "== Patch notes =="
sed -n '1,220p' "$TMP/PATCH_NOTES.md" || true
rm -rf "$TMP"

echo "== Validate Python =="
python3 -m compileall -q src
python3 -m py_compile scripts/seed-governance-test-data.py scripts/reset-governance-test-data.py scripts/generate-governance-traffic.py

echo "== Validate fixture tests =="
if command -v uv >/dev/null 2>&1; then
  uv run --no-project --with pytest --with pyyaml pytest tests/test_augmented_fixtures.py -q
else
  python3 -m pip install --user pytest pyyaml
  python3 -m pytest tests/test_augmented_fixtures.py -q
fi

echo "== Docker compose config =="
docker compose -f docker-compose.yml config >/dev/null
docker compose -f docker-compose.yml -f deploy/gcp/docker-compose.production.yml --env-file deploy/gcp/.env.production.example config >/dev/null

echo "== Changed files =="
git status --short
git diff --stat

echo "== Commit and push =="
git add "${FILES[@]}"
git commit -m "$COMMIT_MSG"
git push origin "$BRANCH"

echo "DONE: committed and pushed governance test-data augmentation."
