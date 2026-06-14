import React, { useEffect, useState } from "react";
import { api, canAdmin } from "../api/client.js";

const LIST_FIELDS = [
  ["readable_namespaces", "Readable namespaces", "namespaces", true],
  ["writable_namespaces", "Writable namespaces", "namespaces", true],
  ["allowed_model_regions", "Allowed model regions", "model_regions", false],
  ["allowed_providers", "Allowed providers (empty = any)", "providers", false],
  ["allowed_model_ids", "Allowed model ids (empty = any)", "model_ids", true],
  ["allowed_model_purposes", "Allowed model purposes", "model_purposes", false],
  ["egress_domains", "Egress domains (* = any)", "egress_suggestions", true],
  ["allowed_retention_classes", "Allowed retention classes", "retention_classes", false],
  ["allowed_runtime_languages", "Allowed runtime languages", "runtime_languages", true],
  ["dual_control_actions", "Dual-control actions", "dual_control_actions", false],
];
const CLASS = ["public", "internal", "confidential", "restricted"];
const TIERS = ["T1", "T2", "T3"];
const ADMIN_SCOPES = ["none", "tenant", "platform"];
const AUDIT_SCOPES = ["none", "own", "team", "tenant", "all"];
const PII = ["none", "masked", "full"];
const RETENTION = ["ephemeral", "standard", "long", "legal-hold"];
const APPROVE = ["none", "team", "tenant", "platform"];
const IMPERSONATE = ["none", "read", "full"];
const FALLBACK = ["strict", "degrade_local"];
const NET = ["none", "allowlist"];
const SELECTS = [
  ["pii_scope", "PII scope", PII, "none"],
  ["max_export_classification", "Max export classification", CLASS, "internal"],
  ["max_retention_class", "Max retention class", RETENTION, "standard"],
  ["fallback_mode", "Model fallback mode", FALLBACK, "degrade_local"],
  ["runtime_network", "Runtime network", NET, "none"],
  ["can_approve", "Can approve (scope)", APPROVE, "none"],
  ["can_impersonate", "Can impersonate", IMPERSONATE, "none"],
];
const NUMS = [
  ["max_input_tokens", "Max input tokens"],
  ["max_output_tokens", "Max output tokens"],
  ["max_tool_calls_per_request", "Max tool calls / request"],
  ["token_budget_per_day", "Token budget/day (0=∞)"],
  ["rate_limit_per_minute", "Rate limit/min (0=default)"],
  ["daily_request_quota", "Daily request quota (0=∞)"],
  ["max_concurrent_requests", "Max concurrent (0=∞) • not yet enforced"],
  ["runtime_max_seconds", "Runtime max seconds"],
  ["runtime_memory_mb", "Runtime memory MB"],
  ["session_max_minutes", "Session max minutes (0=default)"],
];
const BOOLS = [
  ["runtime_exec", "runtime.exec allowed"],
  ["can_manage_users", "can manage users"],
  ["can_manage_roles", "can manage roles"],
  ["can_manage_teams", "can manage teams"],
  ["can_edit_governance", "can edit governance"],
  ["can_register_skills", "can register skills"],
  ["can_delete_tenant", "can delete tenant"],
  ["can_export", "can export data"],
  ["can_erase", "can erase (right-to-erasure)"],
  ["erase_requires_approval", "erase requires approval"],
  ["residency_strict", "strict residency (no cross-region fallback)"],
  ["can_rotate_secrets", "can rotate secrets"],
  ["can_view_traces", "can view traces"],
  ["can_manage_signing_keys", "can manage signing keys"],
];

// The CORE governance set shown by default; everything else lives under "Advanced". Several of these
// (read/write classification, max_output_tokens, token_budget_per_day, write_requires_approval_above)
// are also what the VALUES cascade can tighten, so values and capabilities meet on the same fields.
const CORE_LIST = new Set(["readable_namespaces", "writable_namespaces"]);
const CORE_SELECT = new Set(["pii_scope"]);
const CORE_NUM = new Set(["max_output_tokens", "token_budget_per_day"]);
const CORE_BOOL = new Set(["runtime_exec", "residency_strict", "can_edit_governance", "can_manage_users"]);

export default function Governance() {
  const [tenants, setTenants] = useState([]);
  const [tid, setTid] = useState("");
  const [roles, setRoles] = useState([]);
  const [rid, setRid] = useState("");
  const [caps, setCaps] = useState(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [adv, setAdv] = useState(false);
  const [allSkills, setAllSkills] = useState([]);
  const [allTools, setAllTools] = useState([]);
  const [vocab, setVocab] = useState({});
  const [customVals, setCustomVals] = useState({});

  useEffect(() => {
    if (canAdmin()) {
      api("/admin/tenants", { admin: true }).then((r) => setTenants(r.tenants || [])).catch((e) => setErr(String(e.message || e)));
      api("/admin/skills", { admin: true }).then((r) => setAllSkills(r.skills || [])).catch(() => {});
      api("/admin/tools", { admin: true }).then((r) => setAllTools(r.tools || [])).catch(() => {});
      api("/admin/vocab", { admin: true }).then(setVocab).catch(() => {});
    }
  }, []);

  async function pickTenant(t) {
    setTid(t); setRid(""); setCaps(null); setMsg("");
    if (!t) { setRoles([]); return; }
    try { const d = await api(`/admin/tenants/${t}`, { admin: true }); setRoles(d.roles || []); }
    catch (e) { setErr(String(e.message || e)); }
  }
  function pickRole(r) {
    setRid(r); setMsg("");
    const role = roles.find((x) => x.role_id === r);
    setCaps(role ? { ...role.capabilities } : null);
  }
  function addCustom(f, v) {
    const val = (v || "").trim();
    if (!val) return;
    const cur = caps[f] || [];
    if (!cur.includes(val)) setCaps({ ...caps, [f]: [...cur, val] });
  }
  function setVal(f, v) { setCaps({ ...caps, [f]: v }); }
  function toggle(field, val) {
    const cur = new Set(caps[field] || []);
    cur.has(val) ? cur.delete(val) : cur.add(val);
    setCaps({ ...caps, [field]: [...cur] });
  }

  async function save() {
    setBusy(true); setErr(""); setMsg("");
    try {
      await api(`/admin/tenants/${tid}/roles/${rid}/capabilities`, { method: "PUT", admin: true, body: { capabilities: caps } });
      setMsg("Saved and synced to OPA — enforced on the next request.");
    } catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  // ---- field renderers (shared between core and advanced) ----
  function listField([f, label, vkey, allowCustom]) {
    const selected = caps[f] || [];
    const opts = (vocab[vkey] || []).filter((o) => !selected.includes(o));
    return (
      <div key={f} className="multi">
        <span className="multi-label">{label}</span>
        <div className="chips">
          {selected.map((v) => (
            <span key={v} className="chip">{v}
              <button type="button" onClick={() => toggle(f, v)}>×</button></span>
          ))}
          {selected.length === 0 && <small className="muted">none</small>}
        </div>
        <div className="row multi-add">
          <select value="" onChange={(e) => { if (e.target.value) toggle(f, e.target.value); }}>
            <option value="">+ add from list…</option>
            {opts.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          {allowCustom && (
            <span className="custom-wrap">
              <input className="custom-add" placeholder="custom…" value={customVals[f] || ""}
                     onChange={(e) => setCustomVals({ ...customVals, [f]: e.target.value })} />
              <button type="button" className="ghost"
                      onClick={() => { addCustom(f, customVals[f]); setCustomVals({ ...customVals, [f]: "" }); }}>Add</button>
            </span>
          )}
        </div>
      </div>
    );
  }
  function sel(f, label, opts, def) {
    return (
      <label key={f}>{label}
        <select value={caps[f] || def} onChange={(e) => setVal(f, e.target.value)}>
          {opts.map((x) => <option key={x}>{x}</option>)}
        </select>
      </label>
    );
  }
  function numField([f, label]) {
    return (
      <label key={f}>{label}
        <input type="number" value={caps[f] || 0} onChange={(e) => setVal(f, Number(e.target.value))} />
      </label>
    );
  }
  function boolField([f, label]) {
    return (
      <label key={f} className="row">
        <input type="checkbox" checked={!!caps[f]} onChange={(e) => setVal(f, e.target.checked)} /> {label}
      </label>
    );
  }

  if (!canAdmin()) return <div className="card warn">You don't have administrative access for this view.</div>;

  const advCount =
    LIST_FIELDS.filter(([f]) => !CORE_LIST.has(f)).length + 3 +
    SELECTS.filter(([f]) => !CORE_SELECT.has(f)).length +
    NUMS.filter(([f]) => !CORE_NUM.has(f)).length +
    BOOLS.filter(([f]) => !CORE_BOOL.has(f)).length;

  return (
    <div className="grid2">
      <div className="card">
        <h2>Governance editor</h2>
        {err && <div className="error">{err}</div>}
        <label>Tenant
          <select value={tid} onChange={(e) => pickTenant(e.target.value)}>
            <option value="">Select…</option>
            {tenants.map((t) => <option key={t.tenant_id} value={t.tenant_id}>{t.tenant_id}</option>)}
          </select>
        </label>
        <label>Role
          <select value={rid} disabled={!tid} onChange={(e) => pickRole(e.target.value)}>
            <option value="">Select…</option>
            {roles.map((r) => <option key={r.role_id} value={r.role_id}>{r.role_id}</option>)}
          </select>
        </label>
        <small>Edits write the role's capabilities and re-sync OPA — enforced immediately. The
          Values tab shows how org/team values further tighten these per team.</small>
      </div>

      <div className="card">
        <h2>Capabilities <small className="muted">core</small></h2>
        {!caps && <small className="muted">Pick a tenant and role to edit.</small>}
        {caps && (
          <div className="cols">
            {/* Skills are open to every authenticated user. Per-skill
                governance happens via the actions the skill executes
                (memory.read, tool.call, model.call) which remain role-gated.
                The Skills picker was removed in tandem with the policy.py /
                Rego rule change. */}
            {/* Tools are open to every authenticated user, mirroring the
                skills policy. The catalog picker was removed; per-tool
                governance happens via egress allowlist + DLP. */}
            {/* Readable / writable namespace pickers were also removed:
                memory.read and memory.write are tenant-scoped (the SQL store
                filters on tenant_id before similarity ranking) so within a
                tenant every authenticated user can read / write any
                namespace, subject to the classification ceilings below. */}
            {sel("max_read_classification", "Max read classification", CLASS, "internal")}
            {sel("max_write_classification", "Max write classification", CLASS, "internal")}
            {sel("write_requires_approval_above", "Writes above this classification need approval", CLASS, "restricted")}
            {sel("admin_scope", "Admin scope", ADMIN_SCOPES, "none")}
            {sel("audit_scope", "Audit scope", AUDIT_SCOPES, "own")}
            {SELECTS.filter(([f]) => CORE_SELECT.has(f)).map(([f, l, o, d]) => sel(f, l, o, d))}
            {NUMS.filter(([f]) => CORE_NUM.has(f)).map(numField)}
            {BOOLS.filter(([f]) => CORE_BOOL.has(f)).map(boolField)}

            <button type="button" className="ghost" style={{ margin: "10px 0" }} onClick={() => setAdv(!adv)}>
              {adv ? "Hide advanced capabilities" : `Show advanced capabilities (${advCount} more)`}
            </button>

            {adv && (
              <div className="cols">
                {LIST_FIELDS.filter(([f]) => !CORE_LIST.has(f)).map(listField)}
                {sel("max_model_risk_tier", "Max model risk tier", TIERS, "T3")}
                {sel("require_local_above_classification", "Require local model above classification", CLASS, "restricted")}
                <label>Max summary words
                  <input type="number" value={caps.max_summary_words || 0} onChange={(e) => setVal("max_summary_words", Number(e.target.value))} />
                </label>
                {SELECTS.filter(([f]) => !CORE_SELECT.has(f)).map(([f, l, o, d]) => sel(f, l, o, d))}
                {NUMS.filter(([f]) => !CORE_NUM.has(f)).map(numField)}
                {BOOLS.filter(([f]) => !CORE_BOOL.has(f)).map(boolField)}
              </div>
            )}

            <button onClick={save} disabled={busy}>{busy ? "Saving…" : "Save capabilities"}</button>
            <small className="muted">Budgets, daily quotas and per-role rate limits are enforced (v1.7.0). "Max concurrent" is recorded but not yet enforced.</small>
            {msg && <div className="ok-msg">{msg}</div>}
          </div>
        )}
      </div>
    </div>
  );
}
