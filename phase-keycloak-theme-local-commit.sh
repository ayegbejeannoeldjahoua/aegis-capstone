#!/usr/bin/env bash
set -euo pipefail

REPO="/mnt/c/Users/noelg/Documents/Other Documents/Industry project experimentation/ChatGPT_Enterprise AI agentic system/26062026/aegis"
PATCH_ZIP="/mnt/c/Users/noelg/Documents/Other Documents/Industry project experimentation/ChatGPT_Enterprise AI agentic system/26062026/aegis-keycloak-figma-login-theme-patch-2026-06-26.zip"
BRANCH="main"
COMMIT_MSG="auth: use figma-styled keycloak login theme"

echo "=================================================="
echo " PART 1: Apply Keycloak Figma login theme patch"
echo "=================================================="

cd "$REPO"

echo
echo "1) Repo:"
pwd
git remote -v

if [ ! -f "$PATCH_ZIP" ]; then
  echo "ERROR: Patch ZIP not found:"
  echo "$PATCH_ZIP"
  exit 1
fi

echo
echo "2) Clean generated files first..."

rm -rf frontend/node_modules frontend/dist node_modules dist
git restore frontend/package-lock.json package-lock.json 2>/dev/null || true

echo
echo "3) Backup current repo..."

cd ..
BACKUP_ZIP="aegis-PRE-keycloak-theme-$(date +%F-%H%M).zip"
zip -qr "$BACKUP_ZIP" aegis
echo "Backup created: $(pwd)/$BACKUP_ZIP"
cd "$REPO"

echo
echo "4) Verify patch ZIP contents..."

python3 - "$PATCH_ZIP" <<'PY'
import sys, zipfile
from pathlib import PurePosixPath

zip_path = sys.argv[1]

required = {
    "PATCH_NOTES.md",
    "frontend/src/main.jsx",
    "frontend/src/auth/keycloak.js",
    "frontend/src/pages/SignIn.jsx",
    "frontend/src/styles.css",
    "deploy/keycloak/realm-aegis.json",
    "deploy/keycloak/themes/aegis/login/theme.properties",
    "deploy/keycloak/themes/aegis/login/login.ftl",
    "deploy/keycloak/themes/aegis/login/resources/css/aegis-login.css",
    "deploy/keycloak/apply-aegis-theme.sh",
    "docker-compose.yml",
    "deploy/gcp/redeploy.sh",
}

forbidden = {
    "node_modules",
    "dist",
    ".env",
    ".git",
    ".ruff_cache",
    ".pytest_cache",
}

with zipfile.ZipFile(zip_path) as z:
    names = set(z.namelist())

    missing = required - names
    if missing:
        raise SystemExit(f"ERROR: Missing required files: {sorted(missing)}")

    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"ERROR: Unsafe path in ZIP: {name}")
        if any(part in forbidden for part in path.parts):
            raise SystemExit(f"ERROR: Forbidden generated/secret path in ZIP: {name}")

print("Patch ZIP is valid.")
PY

echo
echo "5) Apply patch files..."

TMP="$(mktemp -d)"
unzip -q "$PATCH_ZIP" -d "$TMP"

FILES=(
  "frontend/src/main.jsx"
  "frontend/src/auth/keycloak.js"
  "frontend/src/pages/SignIn.jsx"
  "frontend/src/styles.css"
  "deploy/keycloak/realm-aegis.json"
  "deploy/keycloak/themes/aegis/login/theme.properties"
  "deploy/keycloak/themes/aegis/login/login.ftl"
  "deploy/keycloak/themes/aegis/login/resources/css/aegis-login.css"
  "deploy/keycloak/apply-aegis-theme.sh"
  "docker-compose.yml"
  "deploy/gcp/redeploy.sh"
)

for f in "${FILES[@]}"; do
  mkdir -p "$(dirname "$f")"
  cp "$TMP/$f" "$f"
done

chmod +x deploy/keycloak/apply-aegis-theme.sh deploy/gcp/redeploy.sh

echo
echo "Patch notes:"
echo "----------------------------------------"
sed -n '1,220p' "$TMP/PATCH_NOTES.md" || true
echo "----------------------------------------"

rm -rf "$TMP"

echo
echo "6) Current changes:"
git status --short
git diff --stat

echo
echo "7) Validate source files..."

python3 -m compileall -q src

python3 - <<'PY'
from pathlib import Path
import json
import tomllib

skip_parts = {
    "node_modules",
    "dist",
    ".git",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
}

tomllib.loads(Path("pyproject.toml").read_text())
print("TOML OK: pyproject.toml")

bad = []
for p in Path(".").rglob("*.json"):
    if any(part in skip_parts for part in p.parts):
        continue
    try:
        json.loads(p.read_text())
        print("JSON OK:", p)
    except Exception as e:
        bad.append((str(p), str(e)))

if bad:
    print("\nBAD JSON FILES:")
    for path, err in bad:
        print(path, "=>", err)
    raise SystemExit(1)
PY

python3 - <<'PY'
from pathlib import Path

skip_parts = {
    "node_modules",
    "dist",
    ".git",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
}

try:
    import yaml
except Exception:
    print("PyYAML not installed; skipping YAML parse.")
    raise SystemExit(0)

for p in list(Path(".").rglob("*.yml")) + list(Path(".").rglob("*.yaml")):
    if any(part in skip_parts for part in p.parts):
        continue
    yaml.safe_load(p.read_text())
    print("YAML OK:", p)
PY

echo
echo "8) Shell syntax check..."

find . \
  -path "./frontend/node_modules" -prune -o \
  -path "./node_modules" -prune -o \
  -path "./.git" -prune -o \
  -name "*.sh" -print0 \
| xargs -0 -I{} bash -n {}

echo
echo "9) Frontend build..."

if ! command -v npm >/dev/null 2>&1; then
  sudo apt update
  sudo apt install -y nodejs npm
fi

cd frontend
npm install
npm run build
cd ..

echo
echo "10) Remove generated files after build..."

rm -rf frontend/node_modules frontend/dist node_modules dist
git restore frontend/package-lock.json package-lock.json 2>/dev/null || true

echo
echo "11) Final changes:"
git status --short
git diff --stat

echo
echo "12) Stage intended files only..."

git add "${FILES[@]}"

echo
echo "13) Staged status:"
git status --short

echo
echo "14) Commit..."

if git diff --cached --quiet; then
  echo "No staged changes. Nothing to commit."
else
  git commit -m "$COMMIT_MSG"
fi

echo
echo "15) Push..."

git push origin "$BRANCH"

echo
echo "=================================================="
echo "PART 1 DONE: patch committed and pushed"
echo "=================================================="
