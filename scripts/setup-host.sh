#!/usr/bin/env bash
# Host prerequisites for the Aegis AI Governance Platform demo on Debian/Ubuntu WSL.
# These are HOST tools (curl/jq/zip); the API's Python deps install inside the container.
# Run once:  bash scripts/setup-host.sh
set -euo pipefail
echo "== Aegis AI Governance Platform :: host prerequisite setup =="
if ! command -v apt-get >/dev/null 2>&1; then
  echo "Targets Debian/Ubuntu (apt). Install equivalents of: jq curl zip unzip ca-certificates"; exit 1
fi
sudo apt-get update -y
sudo apt-get install -y jq curl zip unzip ca-certificates
echo "== Docker check =="
command -v docker >/dev/null 2>&1 && docker --version || echo "WARNING: install Docker Desktop + WSL integration"
docker compose version >/dev/null 2>&1 && docker compose version || echo "WARNING: 'docker compose' v2 unavailable"
echo "== Optional Ollama (only for generated answers) =="
command -v ollama >/dev/null 2>&1 && echo "ollama present; run: ollama pull llama3.1:8b" || echo "ollama not found (optional)"
echo "Host setup complete. Next: cp .env.example .env && docker compose up -d --build"
