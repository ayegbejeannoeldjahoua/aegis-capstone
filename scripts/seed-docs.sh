#!/usr/bin/env bash
# =============================================================================
# seed-docs.sh - seed each tenant's MongoDB document corpus and grant roles the
# namespaces needed to read their team's documents.
#
# For every tenant it: (1) seeds one document per (team x classification) into the
# tenant's Mongo DB via the admin API, and (2) grants each role its own team as a
# readable namespace plus the doc_search tool, so governed retrieval works.
# Idempotent. Requires curl + jq; run after the stack is up + bootstrap/seed-test-org.
#   bash scripts/seed-docs.sh
# =============================================================================
set -uo pipefail
API="${AEGIS_API:-http://localhost:8080}"
TOKEN="${AEGIS_ADMIN_TOKEN:-change-me-admin-token}"
TENANTS="${AEGIS_TENANTS:-it acme-corp beta-corp}"
H=(-H "X-Admin-Token: ${TOKEN}" -H "Content-Type: application/json")
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq required"; exit 1; }

call() {  # method path [body]
  local m="$1" p="$2" b="${3:-}"
  if [ -n "$b" ]; then
    curl -s -o /tmp/sd.out -w '%{http_code}' "${H[@]}" -X "$m" "${API}${p}" -d "$b"
  else
    curl -s -o /tmp/sd.out -w '%{http_code}' "${H[@]}" -X "$m" "${API}${p}"
  fi
}

for t in $TENANTS; do
  echo "== $t =="
  echo "  seed docs -> $(call POST "/admin/tenants/$t/docs/seed")  $(cat /tmp/sd.out)"
  detail=$(curl -s "${H[@]}" "${API}/admin/tenants/$t")
  echo "$detail" | jq -c '.roles[]?' | while read -r role; do
    rid=$(echo "$role" | jq -r '.role_id')
    team=$(echo "$role" | jq -r '.team_id')
    caps=$(echo "$role" | jq -c --arg team "$team" '
      .capabilities
      | .readable_namespaces = ((.readable_namespaces // []) + [$team] | unique)
      | .tools = ((.tools // []) + ["doc_search"] | unique)')
    rc=$(call PUT "/admin/tenants/$t/roles/$rid/capabilities" "$(jq -nc --argjson c "$caps" '{capabilities:$c}')")
    echo "  grant $rid (+ns:$team, +doc_search) -> $rc"
  done
done

echo "== done — document counts: =="
for t in $TENANTS; do
  echo "  $t: $(curl -s "${H[@]}" "${API}/admin/tenants/$t/docs" | jq -r '.count // "?"') docs"
done
