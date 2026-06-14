#!/usr/bin/env bash
# =============================================================================
# test-governance.sh - assert the governance policy directly against OPA.
#
# Queries the PDP decision document (data.aegis.rbac is already synced by the
# API) for the capability / classification / tenant-isolation rules from the
# governance playbook, and prints PASS/FAIL per check. No OIDC token and no model
# backend are required - this exercises the policy logic in isolation.
#
# Prereqs: the stack is up and bootstrap.sh has run (so OPA holds the rbac data
# and the policy). Requires curl + jq.
#   bash scripts/test-governance.sh
# Exit code: 0 if all checks pass, 1 if any fail, 2 on setup error.
# =============================================================================
set -uo pipefail

OPA="${OPA_URL:-http://localhost:8181}"
TENANT="${AEGIS_TEST_TENANT:-acme-corp}"   # uses the seeded roles analyst/lead/viewer/platform-admin
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required (sudo apt-get install -y jq)"; exit 2; }

pass=0; fail=0

# Build a policy input: inp <role> <action> <resource-json>. The resource gets the
# subject's tenant unless the resource-json supplies its own tenant_id (isolation tests).
inp() {
  jq -nc --arg t "$TENANT" --arg role "$1" --arg act "$2" --argjson res "$3" \
    '{subject:{tenant_id:$t, role:$role}, action:$act, resource:({tenant_id:$t} + $res)}'
}

check() {  # check "<desc>" <expected true|false> <input-json>
  local desc="$1" exp="$2" input="$3" got
  got=$(curl -s "$OPA/v1/data/aegis/authz/result" -H 'content-type: application/json' \
        -d "{\"input\": $input}" | jq -r '.result.allow // "ERR"')
  if [ "$got" = "$exp" ]; then
    printf '  \033[32mPASS\033[0m  %s\n' "$desc"; pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m  %s  (expected allow=%s, got %s)\n' "$desc" "$exp" "$got"; fail=$((fail+1))
  fi
}

# ---- preflight ------------------------------------------------------------
if ! curl -fsS "$OPA/health" >/dev/null 2>&1; then
  echo "ERROR: OPA not reachable at $OPA"; exit 2
fi
have=$(curl -s "$OPA/v1/data/aegis/rbac" | jq -r --arg t "$TENANT" '.result[$t] // empty')
if [ -z "$have" ]; then
  echo "ERROR: OPA has no rbac data for tenant '$TENANT'. Bring the stack up and run bootstrap.sh."; exit 2
fi
echo "Testing governance policy for tenant '$TENANT' via $OPA"
echo

echo "[Capability enforcement]"
check "viewer  cannot invoke a skill"              false "$(inp viewer  skill.invoke '{"skill_id":"summarise-with-memory"}')"
check "analyst can invoke summarise-with-memory"   true  "$(inp analyst skill.invoke '{"skill_id":"summarise-with-memory"}')"
check "viewer  cannot read team-decisions"         false "$(inp viewer  memory.read '{"namespace":"team-decisions"}')"
check "lead    can read team-decisions"            true  "$(inp lead    memory.read '{"namespace":"team-decisions"}')"
check "analyst cannot write team-decisions"        false "$(inp analyst memory.write '{"namespace":"team-decisions"}')"
check "lead    can write team-decisions"           true  "$(inp lead    memory.write '{"namespace":"team-decisions","classification":"internal"}')"
check "viewer  cannot call external_lookup tool"   false "$(inp viewer  tool.call '{"tool_id":"external_lookup"}')"
check "analyst can call external_lookup tool"      true  "$(inp analyst tool.call '{"tool_id":"external_lookup"}')"
check "analyst model.call blocked outside region"  false "$(inp analyst model.call '{"region":"US1","provider":"ollama"}')"
check "analyst model.call ok in AC1"               true  "$(inp analyst model.call '{"region":"AC1","provider":"ollama"}')"
check "analyst cannot runtime.exec"                false "$(inp analyst runtime.exec '{"network":"none"}')"
check "lead    can runtime.exec (network none)"    true  "$(inp lead    runtime.exec '{"network":"none"}')"
check "lead    runtime.exec blocked with network"  false "$(inp lead    runtime.exec '{"network":"bridge"}')"

echo
echo "[Classification ceilings]"
check "analyst write internal     -> allow"        true  "$(inp analyst memory.write '{"namespace":"analyst-notes","classification":"internal"}')"
check "analyst write confidential -> deny"         false "$(inp analyst memory.write '{"namespace":"analyst-notes","classification":"confidential"}')"
check "lead    write confidential -> allow"        true  "$(inp lead    memory.write '{"namespace":"analyst-notes","classification":"confidential"}')"
check "lead    write restricted   -> deny"         false "$(inp lead    memory.write '{"namespace":"analyst-notes","classification":"restricted"}')"
check "platadm write restricted   -> allow"        true  "$(inp platform-admin memory.write '{"namespace":"analyst-notes","classification":"restricted"}')"

echo
echo "[Tenant isolation]"
check "cross-tenant read -> deny"                  false "$(inp analyst memory.read '{"namespace":"analyst-notes","tenant_id":"beta-corp"}')"
check "same-tenant read  -> allow (control)"       true  "$(inp analyst memory.read '{"namespace":"analyst-notes"}')"

echo
echo "[Fail-safe defaults]"
check "unknown role denied (no capabilities)"      false "$(inp ghost-role skill.invoke '{"skill_id":"summarise-with-memory"}')"

echo
echo "[v1.6.0 — model purpose & output-token ceiling]"
check "analyst model purpose embedding -> allow" true  "$(inp analyst model.call '{"region":"AC1","provider":"ollama","purpose":"embedding"}')"
check "analyst model purpose vision    -> deny"  false "$(inp analyst model.call '{"region":"AC1","provider":"ollama","purpose":"vision"}')"
check "viewer  output 256 tokens       -> allow" true  "$(inp viewer  model.call '{"region":"AC1","purpose":"chat","max_output_tokens":256}')"
check "viewer  output 2000 tokens      -> deny"  false "$(inp viewer  model.call '{"region":"AC1","purpose":"chat","max_output_tokens":2000}')"

echo
echo "[v1.6.0 — tool egress allowlist]"
check "analyst web_fetch wikipedia.org -> allow" true  "$(inp analyst tool.call '{"tool_id":"web_fetch","egress_domain":"wikipedia.org"}')"
check "analyst web_fetch evil.com      -> deny"  false "$(inp analyst tool.call '{"tool_id":"web_fetch","egress_domain":"evil.com"}')"

echo
echo "[v1.6.0 — data export]"
check "analyst export internal     -> deny (no can_export)" false "$(inp analyst data.export '{"classification":"internal"}')"
check "lead    export internal     -> allow"               true  "$(inp lead data.export '{"classification":"internal"}')"
check "lead    export confidential -> deny"                false "$(inp lead data.export '{"classification":"confidential"}')"
check "platadm export restricted   -> allow"               true  "$(inp platform-admin data.export '{"classification":"restricted"}')"

echo
echo "[v1.6.0 — runtime language & PII scope]"
check "lead   runtime python -> allow" true  "$(inp lead runtime.exec '{"network":"none","language":"python"}')"
check "lead   runtime ruby   -> deny"  false "$(inp lead runtime.exec '{"network":"none","language":"ruby"}')"
check "viewer read PII       -> deny"  false "$(inp viewer  memory.read '{"namespace":"analyst-notes","pii":true}')"
check "analyst read PII      -> allow" true  "$(inp analyst memory.read '{"namespace":"analyst-notes","pii":true}')"

echo
echo "[v1.9.0 — retention & right-to-erasure]"
check "analyst write standard retention   -> allow" true  "$(inp analyst memory.write '{"namespace":"analyst-notes","retention_class":"standard"}')"
check "analyst write legal-hold retention  -> deny"  false "$(inp analyst memory.write '{"namespace":"analyst-notes","retention_class":"legal-hold"}')"
check "lead    write long retention        -> allow" true  "$(inp lead    memory.write '{"namespace":"analyst-notes","retention_class":"long"}')"
check "lead    write legal-hold retention  -> deny"  false "$(inp lead    memory.write '{"namespace":"analyst-notes","retention_class":"legal-hold"}')"
check "analyst memory.delete (no can_erase)-> deny"  false "$(inp analyst memory.delete '{}')"
check "platadm memory.delete               -> allow" true  "$(inp platform-admin memory.delete '{}')"

echo
echo "[v1.10.0 — input tokens & runtime network]"
check "analyst input 100 tokens   -> allow" true  "$(inp analyst model.call '{"region":"AC1","provider":"ollama","purpose":"chat","input_tokens":100}')"
check "analyst input 9000 tokens  -> deny"  false "$(inp analyst model.call '{"region":"AC1","provider":"ollama","purpose":"chat","input_tokens":9000}')"
check "lead runtime network none  -> allow" true  "$(inp lead runtime.exec '{"network":"none","language":"python"}')"
check "lead runtime network bridge-> deny"  false "$(inp lead runtime.exec '{"network":"bridge","language":"python"}')"

echo
echo "-----------------------------------------------"
printf "Result: %d passed, %d failed\n" "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1
