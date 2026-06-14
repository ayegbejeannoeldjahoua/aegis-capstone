import React, { useState } from "react";

// status: undefined = live/enforced; "planned" = recorded in the model, enforcement in an upcoming slice.
const SECTIONS = [
  { title: "How governance works (read me first)", items: [
    { name: "The model", body: "Keycloak proves who you are; the application database decides what you can do. Each role carries a capability record (everything documented below). That record is pushed to the OPA policy engine, so editing a role or template here is a data change that re-syncs and takes effect on the next request — no redeploy." },
    { name: "Source of truth", body: "Your tenant, team and role come from the database assignment keyed on your stable identity (sub) — never trusted from the login token. A user therefore cannot claim a tenant or role they were not assigned." },
    { name: "Defense in depth", body: "Tenant isolation is enforced twice: at the policy layer (the request's tenant must equal the resource's tenant) and at the data layer (every query is filtered by tenant)." },
    { name: "Fail closed", body: "The default decision is deny. If the policy engine is unreachable, requests are refused rather than allowed. Denied actions surface in the chat and Test Console and are written to the audit ledger." },
  ]},
  { title: "Console tabs & controls", items: [
    { name: "Tenants", body: "Create and list tenants; open a tenant to manage its teams and roles, add roles from templates, and (guarded) delete a tenant." },
    { name: "Users", body: "Assign a person to a tenant/team/role, optionally provision a Keycloak login, reset an existing login's password, and move/edit an assignment (cross-tenant moves need platform scope). \u201c(Re)provision login\u201d recreates or refreshes a user's Keycloak login and resets their sub-binding in one click, so an account stranded by a Keycloak reset can sign in again without deleting and recreating the assignment." },
    { name: "Governance", body: "Edit a selected role's capabilities (all fields below). Saving writes the role's capabilities and re-syncs OPA — enforced immediately." },
    { name: "Approvals", body: "The dual-control queue: high-risk actions awaiting a second approver. Approve/Reject here; you cannot approve a request you made yourself." },
    { name: "Audit", body: "Browse the immutable audit ledger (filtered by your audit_scope — platform/all sees the whole ledger), drill into any trace's per-action policy decisions, and verify the SHA-256 hash chain for tamper-evidence." },
    { name: "Catalog", body: "Read-only list of the available skills (with risk tier and signature status) and tools (with side-effect/egress/PII profile)." },
    { name: "Models (platform admin)", body: "Pick the one global model that serves everyone (default ollama/nemotron3:33b). Lists the registered models; only models whose risk tier is \u2264 the viewer ceiling (T2) are eligible as the global default, so the pick routes for every role. The selection is stored in the application DB and takes effect on the next request \u2014 no redeploy. Per-role governance still applies on top." },
    { name: "Test Console", body: "Run a governed request and see its per-action audit trace (each policy decision: allow/deny)." },
    { name: "Account", body: "Change your own password (you must supply your current password)." },
    { name: "Admin token (sidebar)", body: "A break-glass super-admin override (the X-Admin-Token). Normally administrative access comes from your role's admin scope; this bypasses OIDC for ops/bootstrap and should not be used routinely." },
    { name: "Role badge (top bar)", body: "Shows your role and admin scope (or tenant), i.e. the identity the policy engine is evaluating." },
  ]},
  { title: "Capabilities — data access & protection", items: [
    { name: "skills", body: "Which skill workflows the role may invoke (the skill.invoke action). Grant from the catalog dropdown.", values: "any skill_id from the Catalog" },
    { name: "tools", body: "Which tool primitives the role may call (the tool.call action). Grant from the catalog dropdown.", values: "any tool_id from the Catalog" },
    { name: "readable_namespaces", body: "Memory partitions the role may read (memory.read). A read of any other namespace is denied.", values: "e.g. analyst-notes, team-decisions" },
    { name: "writable_namespaces", body: "Memory partitions the role may write (memory.write).", values: "e.g. analyst-notes, team-decisions" },
    { name: "max_read_classification", body: "Highest data classification the role may read; lower classifications are implied.", values: "public < internal < confidential < restricted" },
    { name: "max_write_classification", body: "Highest data classification the role may write.", values: "public < internal < confidential < restricted" },
    { name: "pii_scope", body: "Controls PII exposure. 'none' blocks reads of PII-flagged memory; 'masked' redacts PII (emails, cards, SSNs, phones) in retrieved memory before it reaches the model or caller; 'full' returns it in clear.", values: "none | masked | full" },
    { name: "max_retention_class", body: "Highest retention label the role may assign to memory it writes (enforced on memory.write).", values: "ephemeral < standard < long < legal-hold" },
    { name: "allowed_retention_classes", body: "The set of retention labels the role may set; enforced on memory.write.", values: "subset of ephemeral, standard, long, legal-hold" },
    { name: "can_erase", body: "May delete memory via the governed memory.delete action (right-to-erasure).", values: "on/off" },
    { name: "erase_requires_approval", body: "If set, an erase is queued for dual-control approval (Approvals tab) instead of executing immediately.", values: "on/off" },
    { name: "Per-tenant documents (doc_search)", body: "Each tenant has its own document database (MongoDB). The chat assistant retrieves documents via the governed doc_search tool: you only ever see documents whose team is in your readable_namespaces AND whose classification is within your read ceiling — never another tenant's, another team's, or above your level. Seed a tenant's corpus with scripts/seed-docs.sh (or POST /admin/tenants/{id}/docs/seed)." },
  ]},
  { title: "Capabilities — model routing & cost", items: [
    { name: "allowed_model_regions", body: "Data-residency regions the role may route a model in. A model in another region is refused.", values: "e.g. AC1" },
    { name: "allowed_providers", body: "Provider allowlist for model calls. Empty = any provider.", values: "e.g. ollama, openai, nvidia, vllm, azure_openai" },
    { name: "allowed_model_ids", body: "Specific model allowlist. Empty = any model.", values: "e.g. ollama/llama3.1:8b" },
    { name: "allowed_model_purposes", body: "Which classes of model the role may call. The chat assistant uses 'chat'.", values: "chat, embedding, vision, code" },
    { name: "max_model_risk_tier", body: "Highest model risk tier the role may use; higher-tier models are refused.", values: "T1 < T2 < T3" },
    { name: "require_local_above_classification", body: "At or above this classification, only local models may be routed (data stays on-prem).", values: "public..restricted" },
    { name: "max_output_tokens", body: "Per-call ceiling on model output tokens; a request exceeding it is refused at model.call.", values: "integer" },
    { name: "max_input_tokens", body: "Per-call ceiling on model input tokens; a request whose estimated input exceeds it is refused at model.call.", values: "integer" },
    { name: "fallback_mode", body: "strict = if the preferred model is disallowed, fail rather than route to a fallback; degrade_local = offer the fallback chain.", values: "strict | degrade_local" },
    { name: "residency_strict", body: "When set, the cost-aware fallback chain is dropped so a degrade never crosses provider/region.", values: "on/off" },
  ]},
  { title: "Capabilities — budgets, rate & quota (Redis-backed)", items: [
    { name: "token_budget_per_day", body: "Maximum model tokens per day for the role. Checked before each model call; exceeding returns 429. 0 = unlimited.", values: "integer, 0 = unlimited" },
    { name: "rate_limit_per_minute", body: "Per-role requests allowed per minute (shared across replicas). 0 = use the global default.", values: "integer, 0 = default" },
    { name: "daily_request_quota", body: "Maximum requests per day for the role; exceeding returns 429. 0 = unlimited.", values: "integer, 0 = unlimited" },
    { name: "max_concurrent_requests", body: "Cap on simultaneous in-flight /v1/ask requests for the role; over the cap returns 429. 0 = unlimited.", values: "integer, 0 = unlimited" },
  ]},
  { title: "Capabilities — tools, egress & export", items: [
    { name: "egress_domains", body: "Allowlist of external domains an egress-class tool may reach. '*' = any; empty = no egress (most locked-down).", values: "domains, or *" },
    { name: "can_export", body: "May export data out of the tenant boundary (the data.export action).", values: "on/off" },
    { name: "max_export_classification", body: "Highest classification the role may export.", values: "public..restricted" },
    { name: "max_tool_calls_per_request", body: "Caps how many tool calls a single skill run may make (limits fan-out).", values: "integer" },
  ]},
  { title: "Capabilities — runtime sandbox", items: [
    { name: "runtime_exec", body: "May run sandboxed code (the runtime.exec action).", values: "on/off" },
    { name: "allowed_runtime_languages", body: "Languages permitted in the sandbox; empty = any.", values: "e.g. python, bash" },
    { name: "runtime_network", body: "Sandbox network policy; the runtime.exec gate allows network 'none' or a value matching this.", values: "none | allowlist" },
    { name: "runtime_max_seconds", body: "Per-role sandbox CPU-time cap applied to runtime.exec (falls back to the global default when 0).", values: "integer seconds" },
    { name: "runtime_memory_mb", body: "Per-role sandbox memory cap (MB) applied to runtime.exec (falls back to the global default when 0).", values: "integer MB" },
  ]},
  { title: "Capabilities — platform & governance administration", items: [
    { name: "admin_scope", body: "How far the role's administrative reach extends. 'none' = no admin; 'tenant' = own tenant only; 'platform' = all tenants.", values: "none | tenant | platform" },
    { name: "can_manage_users", body: "May create/move/delete user assignments and reset passwords (within scope)." },
    { name: "can_manage_roles", body: "May add/remove roles in a tenant (within scope)." },
    { name: "can_manage_teams", body: "May add/remove teams in a tenant (within scope)." },
    { name: "can_edit_governance", body: "May edit role capabilities and templates (this screen)." },
    { name: "can_delete_tenant", body: "May delete a tenant (destructive; platform scope). If 'tenant.delete' is in dual_control_actions, it queues for a second approver instead." },
    { name: "can_register_skills", body: "May submit a skill manifest for registration; POST /admin/skills/register validates its Ed25519 signature." },
    { name: "audit_scope", body: "How much of the audit trail the role may read, applied to /v1/audit/* and /admin/traces: own = its own events; tenant = the tenant's; all = cross-tenant. (team falls back to tenant — no team column.)", values: "none | own | team | tenant | all" },
    { name: "can_rotate_secrets", body: "May rotate platform secrets via POST /admin/secrets/rotate (routed through dual control when secret.rotate is in dual_control_actions; demo rotation does not persist)." },
    { name: "can_view_traces", body: "May view trace summaries via GET /admin/traces (derived from the audit ledger)." },
    { name: "can_manage_signing_keys", body: "May view the active skill-signing public key via GET /admin/signing-keys." },
    { name: "can_impersonate", body: "Read-only 'view as': POST /admin/impersonate returns the governance context a target identity would have. No session is issued.", values: "none | read | full" },
    { name: "session_max_minutes", body: "Maximum token age (minutes) accepted; tokens older than this are rejected at authentication. 0 = no cap.", values: "integer minutes, 0 = no cap" },
  ]},
  { title: "Capabilities — approvals & dual control", items: [
    { name: "dual_control_actions", body: "Actions that require a second approver. When a listed action is attempted it is queued in Approvals instead of executing. 'tenant.delete' is wired today.", values: "e.g. tenant.delete, secret.rotate, governance.edit" },
    { name: "can_approve", body: "Whether (and at what scope) the role may approve queued actions. Self-approval is always blocked.", values: "none | team | tenant | platform" },
    { name: "write_requires_approval_above", body: "Classification threshold at/above which a memory write is queued for dual-control approval (Approvals tab) instead of persisting immediately.", values: "public..restricted" },
  ]},
  { title: "Other", items: [
    { name: "max_summary_words", body: "Upper bound on the summary length the summarise skill will produce (also bounded by team/org values rules).", values: "integer" },
  ]},
  { title: "Reference — orders & enums", items: [
    { name: "Classification order", body: "Used by read/write ceilings, export and local-model rules.", values: "public < internal < confidential < restricted" },
    { name: "Model risk tier", body: "Used by max_model_risk_tier.", values: "T1 < T2 < T3" },
    { name: "Admin scope", body: "Breadth of administrative reach.", values: "none < tenant < platform" },
    { name: "Audit scope", body: "Declared audit-read breadth.", values: "none, own, team, tenant, all" },
    { name: "Retention classes", body: "Memory retention labels.", values: "ephemeral, standard, long, legal-hold" },
  ]},
];

export default function Help() {
  const [q, setQ] = useState("");
  const ql = q.trim().toLowerCase();
  const match = (it) => !ql || it.name.toLowerCase().includes(ql)
    || it.body.toLowerCase().includes(ql) || (it.values || "").toLowerCase().includes(ql);

  return (
    <div className="card help">
      <h2>Help &amp; reference</h2>
      <p className="muted">Every element of the console. As of v1.10.0 every capability listed here is
        enforced — by the policy engine, the usage limiter, or a governed admin endpoint.</p>
      <input className="help-search" placeholder="Filter… (e.g. budget, pii, scope, egress, approve)"
             value={q} onChange={(e) => setQ(e.target.value)} />
      {SECTIONS.map((sec) => {
        const items = sec.items.filter(match);
        if (items.length === 0) return null;
        return (
          <section key={sec.title} className="help-sec">
            <h3>{sec.title}</h3>
            <dl>
              {items.map((it) => (
                <div key={it.name} className="help-item">
                  <dt><code>{it.name}</code>{it.status === "planned" && <span className="tag planned">planned</span>}</dt>
                  <dd>{it.body}{it.values && <div className="help-values">Values: {it.values}</div>}</dd>
                </div>
              ))}
            </dl>
          </section>
        );
      })}
    </div>
  );
}
