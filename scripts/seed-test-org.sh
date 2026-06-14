#!/usr/bin/env bash
# =============================================================================
# seed-test-org.sh - lay down a deliberate, multi-tenant test organisation.
#
# Idempotent: safe to re-run. Existing tenants/teams/roles/users are left
# alone (409 conflicts are treated as "already there"); missing ones are
# created. Uses ONLY the admin API (X-Admin-Token), so it works without an
# interactive OIDC login.
#
# What it builds (edit the EDIT-ME blocks below to taste):
#   * it          - global/platform home; teams platform/operations/security;
#                   carries the platform-admin role. pat is MOVED here.
#   * acme-corp   - business tenant; adds finance + legal teams and per-team roles.
#   * beta-corp   - business tenant; adds a support team and per-team roles.
#   * deletes the throwaway tenants gamma-corp and hq (audit ledger retained).
#   * optionally seeds a few test users with logins (CREATE_TEST_USERS=true).
#
# Requirements: curl, jq. Run AFTER the stack is up and bootstrap.sh has run.
#   bash scripts/seed-test-org.sh
# =============================================================================
set -uo pipefail

API="${AEGIS_API:-http://localhost:8080}"
TOKEN="${AEGIS_ADMIN_TOKEN:-change-me-admin-token}"
CREATE_TEST_USERS="${CREATE_TEST_USERS:-true}"
TEST_PASSWORD="${TEST_PASSWORD:-Passw0rd!demo}"   # DEMO ONLY - change for anything real
H=(-H "X-Admin-Token: ${TOKEN}" -H "Content-Type: application/json")

command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required (sudo apt-get install -y jq)"; exit 1; }

# ---- tiny HTTP helper: prints METHOD path -> code; tolerates 'ok' codes -----
call() {  # call METHOD path [json] [tolerated_codes_csv]
  local method="$1" path="$2" body="${3:-}" ok="${4:-200,201,409}"
  local code
  if [ -n "$body" ]; then
    code=$(curl -s -o /tmp/seed.out -w '%{http_code}' "${H[@]}" -X "$method" "${API}${path}" -d "$body")
  else
    code=$(curl -s -o /tmp/seed.out -w '%{http_code}' "${H[@]}" -X "$method" "${API}${path}")
  fi
  if [[ ",$ok," == *",$code,"* ]]; then
    printf '  %-6s %-46s -> %s\n' "$method" "$path" "$code"
  else
    printf '  %-6s %-46s -> %s  !! %s\n' "$method" "$path" "$code" "$(cat /tmp/seed.out)"
  fi
}

add_tenant() { call POST "/admin/tenants" "$(jq -nc --arg t "$1" --arg d "$2" --arg r "${3:-AC1}" '{tenant_id:$t,display_name:$d,region:$r}')"; }
add_team()   { call POST "/admin/tenants/$1/teams" "$(jq -nc --arg t "$2" --arg d "${3:-}" '{team_id:$t} + (if $d=="" then {} else {display_name:$d} end)')"; }
add_role()   { call POST "/admin/tenants/$1/roles" "$(jq -nc --arg r "$2" --arg tm "$3" --arg tpl "$4" '{role_id:$r,team_id:$tm,template_id:$tpl}')"; }
del_tenant() { call DELETE "/admin/tenants/$1" "$(jq -nc --arg c "$1" '{confirm:$c}')" "200,404"; }

# Create a user assignment (+ optional Keycloak login). Tolerates 409 (exists).
add_user() {  # add_user email tenant team role
  local body
  if [ "$CREATE_TEST_USERS" = "true" ]; then
    body=$(jq -nc --arg e "$1" --arg t "$2" --arg tm "$3" --arg r "$4" --arg p "$TEST_PASSWORD" \
            '{email:$e,tenant_id:$t,team_id:$tm,role_id:$r,create_login:true,password:$p}')
  else
    body=$(jq -nc --arg e "$1" --arg t "$2" --arg tm "$3" --arg r "$4" '{email:$e,tenant_id:$t,team_id:$tm,role_id:$r}')
  fi
  call POST "/admin/users" "$body"
}

# Move an existing user (by email) to tenant/team/role, preserving their identity binding.
move_user() {  # move_user email tenant team role
  local email="$1" tenant="$2" team="$3" role="$4" aid cur
  local users; users=$(curl -s "${H[@]}" "${API}/admin/users")
  aid=$(echo "$users" | jq -r --arg e "$email" '.users[] | select((.user_email|ascii_downcase)==($e|ascii_downcase)) | .assignment_id' | head -n1)
  cur=$(echo "$users" | jq -r --arg e "$email" '.users[] | select((.user_email|ascii_downcase)==($e|ascii_downcase)) | .tenant_id' | head -n1)
  if [ -z "$aid" ] || [ "$aid" = "null" ]; then
    echo "  move: no assignment for $email yet - creating one in $tenant/$team/$role"
    add_user "$email" "$tenant" "$team" "$role"
    return
  fi
  if [ "$cur" = "$tenant" ]; then
    echo "  move: $email already in $tenant - updating team/role in place"
  else
    echo "  move: $email $cur -> $tenant (assignment #$aid)"
  fi
  call PUT "/admin/users/${aid}" "$(jq -nc --arg t "$tenant" --arg tm "$team" --arg r "$role" '{tenant_id:$t,team_id:$tm,role_id:$r}')"
}

echo "== Aegis test-org seeding =="
echo "API=$API  CREATE_TEST_USERS=$CREATE_TEST_USERS"
echo

# ============================ EDIT-ME: tenants ===============================
echo "[1/5] Tenants"
add_tenant "it"        "IT Department"     "Canada"
add_tenant "acme-corp" "ACME Corporation"  "AC1"
add_tenant "beta-corp" "Beta Corporation"  "AC1"

# ============================ EDIT-ME: teams =================================
echo "[2/5] Teams"
add_team "it"        "platform"   "Platform"
add_team "it"        "operations" "Operations"
add_team "it"        "security"   "Security"
add_team "acme-corp" "finance"    "Finance"
add_team "acme-corp" "legal"      "Legal"
add_team "beta-corp" "support"    "Support"

# ============================ EDIT-ME: roles =================================
# add_role <tenant> <role_id> <team> <template>
echo "[3/5] Roles"
# it - platform home. platform-admin lives here; plus a tenant-admin and a few staff roles.
add_role "it" "platform-admin" "platform"   "platform-admin"
add_role "it" "it-admin"       "platform"   "tenant-admin"
add_role "it" "it-lead"        "operations" "lead"
add_role "it" "it-analyst"     "operations" "analyst"
add_role "it" "it-viewer"      "security"   "viewer"
# acme-corp - already has analyst/lead/viewer/tenant-admin/platform-admin in research.
add_role "acme-corp" "finance-analyst" "finance" "analyst"
add_role "acme-corp" "finance-lead"    "finance" "lead"
add_role "acme-corp" "legal-viewer"    "legal"   "viewer"
# beta-corp - only had analyst in research; give it a fuller shape.
add_role "beta-corp" "tenant-admin"    "research" "tenant-admin"
add_role "beta-corp" "lead"            "research" "lead"
add_role "beta-corp" "support-lead"    "support"  "lead"
add_role "beta-corp" "support-viewer"  "support"  "viewer"

# ===================== EDIT-ME: users / move pat =============================
echo "[4/5] Users"
# Move platform staff into the global IT tenant (stays platform-admin / global reach).
move_user "pat@acme-corp.example" "it" "platform" "platform-admin"
if [ "$CREATE_TEST_USERS" = "true" ]; then
  # A deliberate spread across tenants / teams / roles / admin levels for testing.
  add_user "itops@it.example"             "it"        "operations" "it-lead"
  add_user "admin-acme@acme-corp.example" "acme-corp" "research"    "tenant-admin"
  add_user "fin-lead@acme-corp.example"   "acme-corp" "finance"     "finance-lead"
  add_user "legal1@acme-corp.example"     "acme-corp" "legal"       "legal-viewer"
  add_user "admin-beta@beta-corp.example" "beta-corp" "research"    "tenant-admin"
  add_user "support1@beta-corp.example"   "beta-corp" "support"     "support-viewer"
  echo "  (test users created with login password: ${TEST_PASSWORD})"
fi

# ===================== EDIT-ME: prune throwaways =============================
echo "[5/5] Cleanup"
del_tenant "gamma-corp"
del_tenant "hq"

echo
echo "== Done. Current tenants: =="
curl -s "${H[@]}" "${API}/admin/tenants" | jq -r '.tenants[] | "  \(.tenant_id)  (\(.role_count) roles)  - \(.display_name)"'
echo "== Assignments: =="
curl -s "${H[@]}" "${API}/admin/users" | jq -r '.users[] | "  \(.user_email)  ->  \(.tenant_id)/\(.team_id)/\(.role_id)  bound=\(.bound)"'
