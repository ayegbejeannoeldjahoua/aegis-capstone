#!/usr/bin/env bash
set -euo pipefail
for url in http://localhost:8080/health http://localhost:8181/health http://localhost:8081/realms/aegis/.well-known/openid-configuration; do
  echo "Waiting for $url"
  for i in {1..60}; do
    if curl -fsS "$url" >/dev/null 2>&1; then break; fi
    sleep 2
    if [[ $i == 60 ]]; then echo "Timed out: $url" >&2; exit 1; fi
  done
done
echo "Stack is ready."
