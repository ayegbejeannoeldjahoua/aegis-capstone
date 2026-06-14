#!/usr/bin/env bash
# import-state.sh - replay the exported governance seed into the running database, e.g.
# after a bare-scratch reinstall (down -v + up + bootstrap). Idempotent (ON CONFLICT /
# guarded inserts), so it is safe to run repeatedly. It does NOT restore passwords or
# sub bindings: re-provision logins afterwards (Provision login / seed-test-org) and let
# users re-bind on first sign-in. For full fidelity incl. passwords use restore.sh.
set -euo pipefail
FILE="${1:-exports/seed-state.sql}"
PGUSER="${POSTGRES_USER:-aegis}"
PGDB="${POSTGRES_DB:-aegis}"
if [ ! -s "$FILE" ]; then
  echo "No seed file at '$FILE' (nothing to import). Run the stack once so the exporter writes it, or pass a path." >&2
  exit 1
fi
echo "Applying governance seed '$FILE' to database '$PGDB' ..."
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$PGDB" < "$FILE"
# Restart the API so it re-syncs OPA from the imported capabilities on startup
# (do NOT run bootstrap.sh here - that would overwrite imported roles with template defaults).
echo "Restarting API to re-sync OPA from the imported governance ..."
docker compose restart api >/dev/null
echo "Done. Re-provision logins (Provision login / seed-test-org) so people can sign in."
