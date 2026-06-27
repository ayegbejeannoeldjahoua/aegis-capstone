#!/usr/bin/env bash
set -euo pipefail

REPO="/mnt/c/Users/noelg/Documents/Other Documents/Industry project experimentation/ChatGPT_Enterprise AI agentic system/26062026/aegis"
PATCH_ZIP="/mnt/c/Users/noelg/Documents/Other Documents/Industry project experimentation/ChatGPT_Enterprise AI agentic system/26062026/aegis-dashboard-governance-metrics-patch-2026-06-27.zip"
BRANCH="main"
COMMIT_MSG="dashboard: add governance operations metrics"

cd "$REPO"

echo "== 1) Check patch ZIP =="
test -f "$PATCH_ZIP"

echo "== 2) Clean generated files =="
rm -rf frontend/node_modules frontend/dist node_modules dist .pytest_cache .ruff_cache
git restore frontend/package-lock.json package-lock.json 2>/dev/null || true

echo "== 3) Backup current repo =="
cd ..
zip -qr "aegis-PRE-dashboard-metrics-$(date +%F-%H%M).zip" aegis
cd "$REPO"

echo "== 4) Extract patch to temp =="
TMP="$(mktemp -d)"
unzip -q "$PATCH_ZIP" -d "$TMP"

echo "== 5) Copy patch files into repo =="
cd "$TMP"

find . \
  -type f \
  ! -path "./.git/*" \
  ! -path "./node_modules/*" \
  ! -path "./frontend/node_modules/*" \
  ! -path "./frontend/dist/*" \
  ! -path "./dist/*" \
  ! -path "./.ruff_cache/*" \
  ! -path "./.pytest_cache/*" \
  ! -name ".env" \
  ! -name ".env.production" \
  ! -name "PATCH_NOTES.md" \
  -print0 \
| while IFS= read -r -d '' f; do
    rel="${f#./}"
    mkdir -p "$REPO/$(dirname "$rel")"
    cp "$f" "$REPO/$rel"
  done

echo "== 6) Patch notes =="
if [ -f "$TMP/PATCH_NOTES.md" ]; then
  sed -n '1,220p' "$TMP/PATCH_NOTES.md"
fi

rm -rf "$TMP"
cd "$REPO"

echo "== 7) Show changed files =="
git status --short
git diff --stat

echo "== 8) Python validation =="
python3 -m compileall -q src

python3 - <<'PY'
from pathlib import Path
import json
import tomllib

skip = {"node_modules", "dist", ".git", ".ruff_cache", ".pytest_cache", "__pycache__"}

tomllib.loads(Path("pyproject.toml").read_text())
print("TOML OK")

bad = []
for p in Path(".").rglob("*.json"):
    if any(part in skip for part in p.parts):
        continue
    try:
        json.loads(p.read_text())
    except Exception as e:
        bad.append((str(p), str(e)))

if bad:
    for path, err in bad:
        print("BAD JSON:", path, err)
    raise SystemExit(1)

print("JSON OK")
PY

echo "== 9) YAML validation if available =="
python3 - <<'PY'
from pathlib import Path

skip = {"node_modules", "dist", ".git", ".ruff_cache", ".pytest_cache", "__pycache__"}

try:
    import yaml
except Exception:
    print("PyYAML not installed; skipping YAML parse.")
    raise SystemExit(0)

for p in list(Path(".").rglob("*.yml")) + list(Path(".").rglob("*.yaml")):
    if any(part in skip for part in p.parts):
        continue
    yaml.safe_load(p.read_text())

print("YAML OK")
PY

echo "== 10) Shell syntax =="
find . \
  -path "./frontend/node_modules" -prune -o \
  -path "./node_modules" -prune -o \
  -path "./.git" -prune -o \
  -name "*.sh" -print0 \
| xargs -0 -I{} bash -n {}

echo "== 11) Frontend build =="
if ! command -v npm >/dev/null 2>&1; then
  sudo apt update
  sudo apt install -y nodejs npm
fi

cd frontend
npm install
npm run build
cd ..

echo "== 12) Docker Compose config =="
docker compose -f docker-compose.yml config >/dev/null
docker compose \
  -f docker-compose.yml \
  -f deploy/gcp/docker-compose.production.yml \
  --env-file deploy/gcp/.env.production.example \
  config >/dev/null

echo "== 13) Remove generated files after build =="
rm -rf frontend/node_modules frontend/dist node_modules dist
git restore frontend/package-lock.json package-lock.json 2>/dev/null || true

echo "== 14) Final changed files =="
git status --short
git diff --stat

echo "== 15) Commit and push =="
git add .

git reset -- frontend/node_modules node_modules frontend/dist dist .pytest_cache .ruff_cache 2>/dev/null || true
git reset -- frontend/package-lock.json package-lock.json 2>/dev/null || true
git reset -- PATCH_NOTES.md 2>/dev/null || true

if git diff --cached --quiet; then
  echo "No staged changes. Nothing to commit."
else
  git commit -m "$COMMIT_MSG"
fi

git push origin "$BRANCH"

echo "DONE: dashboard governance metrics patch committed and pushed."
