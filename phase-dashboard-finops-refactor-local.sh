#!/usr/bin/env bash
set -euo pipefail

REPO="/mnt/c/Users/noelg/Documents/Other Documents/Industry project experimentation/ChatGPT_Enterprise AI agentic system/26062026/aegis"
PATCH_ZIP="/mnt/c/Users/noelg/Documents/Other Documents/Industry project experimentation/ChatGPT_Enterprise AI agentic system/26062026/aegis-dashboard-finops-refactor-patch-2026-06-27.zip"
BRANCH="main"
COMMIT_MSG="dashboard: refactor governance metrics and finops"

cd "$REPO"

echo "== 1) Check patch ZIP =="
test -f "$PATCH_ZIP"

echo "== 2) Clean generated files =="
rm -rf frontend/node_modules frontend/dist node_modules dist .pytest_cache .ruff_cache
git restore frontend/package-lock.json package-lock.json 2>/dev/null || true

echo "== 3) Backup current repo =="
cd ..
zip -qr "aegis-PRE-dashboard-finops-refactor-$(date +%F-%H%M).zip" aegis
cd "$REPO"

echo "== 4) Apply patch safely =="
python3 - "$PATCH_ZIP" "$REPO" <<'PY'
import sys
import zipfile
from pathlib import Path, PurePosixPath

zip_path = Path(sys.argv[1])
repo = Path(sys.argv[2])

forbidden_parts = {
    ".git",
    ".env",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "dist",
}

forbidden_names = {
    ".env",
    ".env.production",
}

with zipfile.ZipFile(zip_path) as z:
    names = z.namelist()
    print("ZIP entries:")
    for name in names:
        print(" -", name)

    for name in names:
        p = PurePosixPath(name)

        if p.is_absolute() or ".." in p.parts:
            raise SystemExit(f"Unsafe ZIP path: {name}")

        if name.endswith("/"):
            continue

        if p.name == "PATCH_NOTES.md":
            continue

        if p.name in forbidden_names:
            raise SystemExit(f"Forbidden file in ZIP: {name}")

        if any(part in forbidden_parts for part in p.parts):
            raise SystemExit(f"Forbidden path in ZIP: {name}")

        target = repo / Path(*p.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(z.read(name))

print("Patch applied.")
PY

echo "== 5) Show patch notes =="
python3 - "$PATCH_ZIP" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    if "PATCH_NOTES.md" in z.namelist():
        print(z.read("PATCH_NOTES.md").decode("utf-8", errors="replace")[:6000])
    else:
        print("No PATCH_NOTES.md found.")
PY

echo "== 6) Current changes =="
git status --short
git diff --stat

echo "== 7) Python validation =="
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

echo "== 8) YAML validation if available =="
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

echo "== 9) Shell syntax =="
find . \
  -path "./frontend/node_modules" -prune -o \
  -path "./node_modules" -prune -o \
  -path "./.git" -prune -o \
  -name "*.sh" -print0 \
| xargs -0 -I{} bash -n {}

echo "== 10) Frontend build =="
if ! command -v npm >/dev/null 2>&1; then
  sudo apt update
  sudo apt install -y nodejs npm
fi

cd frontend
npm install
npm run build
cd ..

echo "== 11) Docker Compose config if Docker exists =="
if command -v docker >/dev/null 2>&1; then
  docker compose -f docker-compose.yml config >/dev/null
  docker compose \
    -f docker-compose.yml \
    -f deploy/gcp/docker-compose.production.yml \
    --env-file deploy/gcp/.env.production.example \
    config >/dev/null
else
  echo "Docker not installed locally; skipping compose config."
fi

echo "== 12) Remove generated files after build =="
rm -rf frontend/node_modules frontend/dist node_modules dist
git restore frontend/package-lock.json package-lock.json 2>/dev/null || true

echo "== 13) Final changes =="
git status --short
git diff --stat

echo "== 14) Commit and push =="
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

echo
echo "DONE: Dashboard/FinOps refactor patch committed and pushed."
