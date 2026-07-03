import React, { useEffect, useMemo, useState } from "react";
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
  const [matrixVersion, setMatrixVersion] = useState(0);

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
      setMatrixVersion((v) => v + 1);
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
    <>
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
    <CapabilityMatrix refreshKey={matrixVersion} />
    </>
  );
}

function decisionTone(decision) {
  if (decision === "allow") return "allow";
  if (decision === "deny") return "deny";
  if (decision === "conditional") return "conditional";
  return "unknown";
}

function listText(items, fallback = "none") {
  if (!Array.isArray(items) || items.length === 0) return fallback;
  return items.join(", ");
}

function CapabilityMatrix({ refreshKey }) {
  const [matrix, setMatrix] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [roleFilter, setRoleFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [decisionFilter, setDecisionFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let alive = true;
    setBusy(true);
    setErr("");
    api("/admin/governance/capability-matrix", { admin: true })
      .then((data) => {
        if (!alive) return;
        setMatrix(data);
        setSelected(null);
      })
      .catch((e) => {
        if (alive) setErr(String(e.message || e));
      })
      .finally(() => {
        if (alive) setBusy(false);
      });
    return () => { alive = false; };
  }, [refreshKey, reloadToken]);

  const actions = matrix?.actions || [];
  const roles = matrix?.roles || [];
  const rows = matrix?.matrix || [];
  const rolesById = useMemo(() => new Map(roles.map((r) => [r.role_id, r])), [roles]);
  const actionsById = useMemo(() => new Map(actions.map((a) => [a.action, a])), [actions]);
  const categories = useMemo(() => ["all", ...Array.from(new Set(actions.map((a) => a.category).filter(Boolean)))], [actions]);

  const visibleActions = actions.filter((action) => categoryFilter === "all" || action.category === categoryFilter);
  const visibleRows = rows
    .filter((row) => roleFilter === "all" || row.role_id === roleFilter)
    .map((row) => ({
      ...row,
      cells: (row.cells || []).filter((cell) => {
        const actionOk = visibleActions.some((a) => a.action === cell.action);
        const decisionOk = decisionFilter === "all" || cell.decision === decisionFilter;
        return actionOk && decisionOk;
      }),
    }))
    .filter((row) => row.cells.length > 0);

  const counts = useMemo(() => {
    const cells = rows.flatMap((row) => row.cells || []);
    return {
      roles: roles.length,
      actions: actions.length,
      allow: cells.filter((c) => c.decision === "allow").length,
      conditional: cells.filter((c) => c.decision === "conditional").length,
      deny: cells.filter((c) => c.decision === "deny").length,
    };
  }, [actions.length, roles.length, rows]);

  return (
    <div className="card capability-matrix-card">
      <div className="capability-matrix-head">
        <div>
          <h2>Capability matrix</h2>
          <p className="muted">
            Backend-computed role decisions across memory, values, models, tools, audit, admin, runtime and tenant isolation.
          </p>
        </div>
        <button type="button" className="ghost" disabled={busy}
                onClick={() => setReloadToken((v) => v + 1)}>
          {busy ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {err && <div className="error">{err}</div>}
      {!matrix && !err && <small className="muted">Loading capability matrix...</small>}

      {matrix && (
        <>
          <div className="capability-summary">
            <div><span>Roles</span><strong>{counts.roles}</strong></div>
            <div><span>Actions</span><strong>{counts.actions}</strong></div>
            <div><span>Conditional</span><strong>{counts.conditional}</strong></div>
            <div><span>Denied</span><strong>{counts.deny}</strong></div>
            <div><span>Admin scope</span><strong>{matrix.scope?.admin_scope || "none"}</strong></div>
          </div>

          <div className="capability-filters">
            <label>Role
              <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                <option value="all">All roles</option>
                {roles.map((role) => <option key={role.role_id} value={role.role_id}>{role.role_id}</option>)}
              </select>
            </label>
            <label>Category
              <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
                {categories.map((category) => (
                  <option key={category} value={category}>{category === "all" ? "All categories" : category}</option>
                ))}
              </select>
            </label>
            <label>Decision
              <select value={decisionFilter} onChange={(e) => setDecisionFilter(e.target.value)}>
                <option value="all">All decisions</option>
                <option value="allow">Allow</option>
                <option value="conditional">Conditional</option>
                <option value="deny">Deny</option>
                <option value="unknown">Unknown</option>
              </select>
            </label>
          </div>

          <div className="capability-matrix-scroll">
            <table className="capability-matrix-table">
              <thead>
                <tr>
                  <th>Role</th>
                  {visibleActions.map((action) => (
                    <th key={action.action}>
                      <span>{action.label}</span>
                      <small>{action.category}</small>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => {
                  const role = rolesById.get(row.role_id) || {};
                  const cellsByAction = new Map((row.cells || []).map((cell) => [cell.action, cell]));
                  return (
                    <tr key={row.role_id}>
                      <th>
                        <strong>{role.display_name || row.display_name || row.role_id}</strong>
                        <small>{row.role_id} · admin {role.admin_scope || "none"} · PII {role.pii_scope || "masked"}</small>
                        <small>read <= {role.classification_scope?.max_read_classification || "n/a"}</small>
                        {Array.isArray(role.persona_examples) && role.persona_examples.length > 0 && (
                          <span className="capability-personas">
                            {role.persona_examples.slice(0, 3).map((p) => <em key={`${p.email}-${p.tenant_id}`}>{p.email}</em>)}
                          </span>
                        )}
                      </th>
                      {visibleActions.map((action) => {
                        const cell = cellsByAction.get(action.action);
                        if (!cell) return <td key={action.action} className="capability-empty-cell">-</td>;
                        return (
                          <td key={action.action}>
                            <button
                              type="button"
                              className={`capability-cell ${decisionTone(cell.decision)}`}
                              onClick={() => setSelected({ cell, role, action })}
                            >
                              <span>{cell.decision}</span>
                              <small>{cell.scope}</small>
                            </button>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {selected && (
            <div className="capability-detail">
              <div>
                <h3>{selected.role.display_name || selected.cell.role_id} / {selected.action.label}</h3>
                <span className={`capability-detail-pill ${decisionTone(selected.cell.decision)}`}>
                  {selected.cell.decision}
                </span>
              </div>
              <p>{selected.cell.reason}</p>
              <dl>
                <div><dt>Scope</dt><dd>{selected.cell.scope}</dd></div>
                <div><dt>Evidence</dt><dd>{listText(selected.cell.evidence_source)}</dd></div>
                <div><dt>Conditions</dt><dd>{listText(selected.cell.conditions)}</dd></div>
                <div><dt>Memory</dt><dd>read {listText(selected.role.memory_scope?.readable_namespaces)} / write {listText(selected.role.memory_scope?.writable_namespaces)}</dd></div>
                <div><dt>Model</dt><dd>{listText(selected.role.model_access?.providers, "any provider")} in {listText(selected.role.model_access?.regions, "configured region")}</dd></div>
                <div><dt>Egress</dt><dd>{selected.role.egress_profile?.mode || "none"}: {listText(selected.role.egress_profile?.domains)}</dd></div>
              </dl>
            </div>
          )}

          <div className="capability-notes">
            {(matrix.notes || []).map((note) => <p key={note}>{note}</p>)}
          </div>

          <div className="capability-scenarios">
            <h3>Scenario mapping</h3>
            <div>
              {(matrix.scenario_map || []).map((scenario) => (
                <span key={scenario.id}>
                  <strong>{scenario.label}</strong>
                  <small>{scenario.persona} · {(scenario.actions || []).map((action) => actionsById.get(action)?.label || action).join(", ")}</small>
                </span>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
