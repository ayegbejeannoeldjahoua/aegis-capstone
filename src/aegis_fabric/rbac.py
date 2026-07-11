"""App-DB-centric RBAC: role templates, per-role capabilities, identity resolution,
and synchronization of the capability map into OPA's data document.

Authorization is data-driven: the database is the source of truth for *what a role
can do*, and that capability map is pushed to OPA (`data.aegis.rbac`) so a single
generic policy can evaluate every action. Adding a tenant or role is a data change,
never a policy-code change.
"""
from __future__ import annotations

import httpx

from pathlib import Path

from .db import get_conn
from .logging_config import get_logger
from .settings import settings

logger = get_logger("aegis.rbac")

# Ordered enums for comparison.
CLASSIFICATION_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
RISK_RANK = {"T1": 1, "T2": 2, "T3": 3}


def class_rank(c: str) -> int:
    return CLASSIFICATION_RANK.get(c, 1)


def classes_up_to(maxc: str) -> list[str]:
    """All classifications at or below `maxc` (what a role may read/write)."""
    r = class_rank(maxc)
    return [c for c, rank in CLASSIFICATION_RANK.items() if rank <= r]


def risk_rank(t: str) -> int:
    return RISK_RANK.get(t, 3)


# Capability schema (the "template"). Defaults are a least-privilege-ish floor that
# still lets an un-restamped legacy role operate at the demo's "internal" level.
EMPTY_CAPS: dict = {
    "skills": [],
    "tools": [],
    "readable_namespaces": [],
    "writable_namespaces": [],
    "allowed_model_regions": [],
    "max_summary_words": 0,
    "runtime_exec": False,
    # data classification limits
    "max_read_classification": "internal",
    "max_write_classification": "internal",
    # model governance
    "allowed_providers": [],          # empty -> no provider restriction
    "allowed_model_ids": [],          # empty -> no model-id restriction
    "max_model_risk_tier": "T3",      # highest model risk tier the role may use
    "require_local_above_classification": "restricted",  # >= this -> local model only
    # admin / governance RBAC over the platform itself
    "admin_scope": "none",            # none | tenant | platform
    "can_manage_users": False,
    "can_manage_roles": False,
    "can_edit_governance": False,
    "can_register_skills": False,
    "audit_scope": "own",             # none | own | team | tenant | all
    "can_delete_tenant": False,       # platform-scoped, destructive
    # --- v1.6.0 capability expansion ---
    # data protection
    "pii_scope": "none",                       # none | masked | full
    "allowed_retention_classes": ["standard"], # which retention labels a role may set
    "max_retention_class": "standard",         # ephemeral | standard | long | legal-hold
    "can_erase": False,                        # right-to-erasure (memory.delete)
    "erase_requires_approval": True,
    # tools / egress / export
    "egress_domains": [],                      # allowlist for egress-class tools; [] = no egress
    "can_export": False,
    "max_export_classification": "internal",
    "max_tool_calls_per_request": 4,
    # model routing & cost
    "allowed_model_purposes": ["chat"],        # chat | embedding | vision | code
    "max_input_tokens": 8192,
    "max_output_tokens": 1024,
    "token_budget_per_day": 0,                 # 0 = unlimited (stateful; enforcement deferred)
    "fallback_mode": "degrade_local",          # strict | degrade_local
    "residency_strict": False,
    # rate / quota / concurrency (stateful; enforcement deferred to v1.6.1)
    "rate_limit_per_minute": 0,                # 0 = use global default
    "daily_request_quota": 0,
    "max_concurrent_requests": 0,
    # runtime sandbox caps
    "runtime_max_seconds": 0,                  # 0 = global default
    "runtime_memory_mb": 0,
    "runtime_network": "none",                 # none | allowlist
    "allowed_runtime_languages": [],
    # human-in-the-loop / dual control (workflow; enforcement deferred to v1.7.0)
    "write_requires_approval_above": "restricted",  # threshold; "restricted" == effectively off
    "dual_control_actions": [],
    "can_approve": "none",                     # none | team | tenant | platform
    # platform governance (extended admin caps)
    "can_manage_teams": False,
    "can_rotate_secrets": False,
    "can_view_traces": False,
    "can_manage_signing_keys": False,
    "can_impersonate": "none",                 # none | read | full
    "session_max_minutes": 0,                  # 0 = default
}

_LIST_FIELDS = {"skills", "tools", "readable_namespaces", "writable_namespaces",
                "allowed_model_regions", "allowed_providers", "allowed_model_ids",
                "egress_domains", "allowed_model_purposes", "allowed_retention_classes",
                "allowed_runtime_languages", "dual_control_actions"}


def normalize_caps(caps: dict | None) -> dict:
    merged = dict(EMPTY_CAPS)
    if caps:
        merged.update({k: caps[k] for k in caps if k in EMPTY_CAPS})
    return merged


def derived_caps(caps: dict) -> dict:
    """Caps plus precomputed lists OPA can match directly (avoids rank logic in Rego)."""
    out = dict(caps)
    out["readable_classifications"] = classes_up_to(caps.get("max_read_classification", "internal"))
    out["writable_classifications"] = classes_up_to(caps.get("max_write_classification", "internal"))
    out["exportable_classifications"] = classes_up_to(caps.get("max_export_classification", "internal"))
    return out


DEFAULT_TEMPLATES: dict[str, dict] = {
    "analyst": {"display_name": "Analyst", "capabilities": {
        "skills": ["assistant", "summarise-with-memory", "research-brief", "qa-over-docs"],
        "tools": ["external_lookup", "web_search", "web_fetch", "kb_search", "vector_recall", "doc_search", "calculator", "db_query"],
        "readable_namespaces": ["analyst-notes"], "writable_namespaces": ["analyst-notes"],
        "allowed_model_regions": ["AC1"], "max_summary_words": 200, "runtime_exec": False,
        "max_read_classification": "confidential", "max_write_classification": "internal",
        "max_model_risk_tier": "T2", "admin_scope": "none", "audit_scope": "own",
        "pii_scope": "masked", "allowed_model_purposes": ["chat", "embedding"],
        "egress_domains": ["wikipedia.org", "example.com"], "max_output_tokens": 2048,
        "max_tool_calls_per_request": 6, "token_budget_per_day": 10_000,
    }},
    "lead": {"display_name": "Lead", "capabilities": {
        "skills": ["assistant", "summarise-with-memory", "research-brief", "qa-over-docs", "meeting-notes"],
        "tools": ["external_lookup", "web_search", "web_fetch", "kb_search", "vector_recall", "doc_search",
                  "calculator", "db_query", "code_exec", "email_send", "redact"],
        "readable_namespaces": ["analyst-notes", "team-decisions"],
        "writable_namespaces": ["analyst-notes", "team-decisions"],
        "allowed_model_regions": ["AC1"], "max_summary_words": 300, "runtime_exec": True,
        "max_read_classification": "confidential", "max_write_classification": "confidential",
        "max_model_risk_tier": "T3", "admin_scope": "none", "audit_scope": "team",
        "pii_scope": "full", "allowed_model_purposes": ["chat", "embedding", "code"],
        "egress_domains": ["wikipedia.org", "example.com"], "max_output_tokens": 8192,
        "max_tool_calls_per_request": 8, "can_export": True, "max_export_classification": "internal",
        "max_retention_class": "long", "allowed_retention_classes": ["ephemeral", "standard", "long"],
        "runtime_max_seconds": 60, "runtime_memory_mb": 512, "runtime_network": "none",
        "allowed_runtime_languages": ["python"], "can_approve": "team", "token_budget_per_day": 20_000,
    }},
    "viewer": {"display_name": "Viewer", "capabilities": {
        "skills": ["assistant", "qa-over-docs", "kb-answer"], "tools": ["kb_search", "vector_recall", "doc_search", "calculator"],
        "readable_namespaces": ["analyst-notes"], "writable_namespaces": [],
        "allowed_model_regions": ["AC1"], "max_summary_words": 200, "runtime_exec": False,
        "max_read_classification": "internal", "max_write_classification": "public",
        "max_model_risk_tier": "T2", "admin_scope": "none", "audit_scope": "own",  # T2: the local 8B model computes to T2; T1 left no routable model
        "pii_scope": "none", "allowed_model_purposes": ["chat"], "max_output_tokens": 512,
        "max_tool_calls_per_request": 2, "token_budget_per_day": 4_000,
    }},
    "tenant-admin": {"display_name": "Tenant Admin", "capabilities": {
        "skills": ["assistant", "summarise-with-memory", "research-brief", "qa-over-docs", "meeting-notes", "access-review"],
        "tools": ["external_lookup", "web_search", "web_fetch", "kb_search", "vector_recall", "doc_search",
                  "calculator", "db_query", "doc_retrieve", "redact"],
        "readable_namespaces": ["analyst-notes", "team-decisions"],
        "writable_namespaces": ["analyst-notes", "team-decisions"],
        "allowed_model_regions": ["AC1"], "max_summary_words": 300, "runtime_exec": False,
        "max_read_classification": "confidential", "max_write_classification": "confidential",
        "max_model_risk_tier": "T3",
        "admin_scope": "tenant", "can_manage_users": True, "can_manage_roles": True,
        "can_edit_governance": True, "can_register_skills": False, "audit_scope": "tenant",
        "pii_scope": "full", "allowed_model_purposes": ["chat", "embedding", "code", "vision"],
        "max_output_tokens": 8192, "can_export": True, "max_export_classification": "confidential",
        "max_retention_class": "legal-hold",
        "allowed_retention_classes": ["ephemeral", "standard", "long", "legal-hold"],
        "can_erase": True, "can_manage_teams": True, "can_approve": "tenant",
        "dual_control_actions": ["governance.edit"], "token_budget_per_day": 24_000,
    }},
    "platform-admin": {"display_name": "Platform Admin", "capabilities": {
        "skills": ["assistant", "summarise-with-memory", "research-brief", "qa-over-docs", "meeting-notes",
                   "access-review", "incident-summary", "audit-digest", "runbook-exec"],
        "tools": ["external_lookup", "web_search", "web_fetch", "kb_search", "vector_recall", "doc_search",
                  "calculator", "db_query", "doc_retrieve", "pdf_extract", "redact", "code_exec",
                  "email_send", "ticket_create", "ticket_update", "crm_lookup", "file_export", "webhook_call"],
        "readable_namespaces": ["analyst-notes", "team-decisions"],
        "writable_namespaces": ["analyst-notes", "team-decisions"],
        "allowed_model_regions": ["AC1"], "max_summary_words": 400, "runtime_exec": True,
        "max_read_classification": "restricted", "max_write_classification": "restricted",
        "max_model_risk_tier": "T3",
        "admin_scope": "platform", "can_manage_users": True, "can_manage_roles": True,
        "can_edit_governance": True, "can_register_skills": True, "audit_scope": "all",
        "can_delete_tenant": True,
        "pii_scope": "full", "allowed_model_purposes": ["chat", "embedding", "code", "vision"],
        "egress_domains": ["*"], "max_output_tokens": 16384, "max_tool_calls_per_request": 16,
        "can_export": True, "max_export_classification": "restricted",
        "max_retention_class": "legal-hold",
        "allowed_retention_classes": ["ephemeral", "standard", "long", "legal-hold"],
        "can_erase": True, "can_manage_teams": True, "can_rotate_secrets": True,
        "can_view_traces": True, "can_manage_signing_keys": True, "can_impersonate": "read",
        "can_approve": "platform", "dual_control_actions": ["tenant.delete", "secret.rotate"],
        "runtime_max_seconds": 120, "runtime_memory_mb": 1024, "allowed_runtime_languages": ["python", "bash"],
        "token_budget_per_day": 40_000,
    }},
}


def template_capabilities(template_id: str) -> dict:
    tmpl = DEFAULT_TEMPLATES.get(template_id)
    return normalize_caps(tmpl["capabilities"]) if tmpl else dict(EMPTY_CAPS)


def role_capabilities(tenant_id: str, role_id: str) -> dict:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT capabilities FROM roles WHERE tenant_id=%s AND role_id=%s",
                (tenant_id, role_id),
            ).fetchone()
    except Exception as e:  # noqa: BLE001
        logger.warning("role_capabilities lookup failed (%s/%s): %s", tenant_id, role_id, e)
        return dict(EMPTY_CAPS)
    if row and row.get("capabilities"):
        return normalize_caps(row["capabilities"])
    return dict(EMPTY_CAPS)


def all_rbac() -> dict:
    """Full {tenant_id: {role_id: derived_capabilities}} map for OPA."""
    out: dict[str, dict] = {}
    with get_conn() as conn:
        rows = conn.execute("SELECT tenant_id, role_id, capabilities FROM roles").fetchall()
    for r in rows:
        out.setdefault(r["tenant_id"], {})[r["role_id"]] = derived_caps(normalize_caps(r.get("capabilities")))
    return out


def sync_opa(data: dict | None = None) -> bool:
    payload = data if data is not None else all_rbac()
    url = f"{settings.opa_url}/v1/data/aegis/rbac"
    try:
        with httpx.Client(timeout=settings.opa_timeout_seconds) as client:
            resp = client.put(url, json=payload)
            resp.raise_for_status()
        logger.info("synced RBAC to OPA (%d tenants)", len(payload))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("OPA RBAC sync failed: %s", e)
        return False


def resolve_assignment(sub: str, email: str | None, email_verified: bool) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT tenant_id, team_id, role_id FROM user_assignments WHERE sub=%s", (sub,)
        ).fetchone()
        if row:
            return dict(row)
        if settings.allow_email_binding and email and email_verified:
            row = conn.execute(
                "SELECT assignment_id, tenant_id, team_id, role_id FROM user_assignments "
                "WHERE sub IS NULL AND lower(user_email)=lower(%s) ORDER BY assignment_id LIMIT 1",
                (email,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE user_assignments SET sub=%s, bound_at=now() WHERE assignment_id=%s",
                    (sub, row["assignment_id"]),
                )
                logger.info("bound sub to assignment for %s", email)
                return {"tenant_id": row["tenant_id"], "team_id": row["team_id"], "role_id": row["role_id"]}
    return None


_REGO_CANDIDATES = [Path("/app/deploy/opa/aegis.rego"), Path("deploy/opa/aegis.rego")]


def _rego_path() -> Path | None:
    for p in _REGO_CANDIDATES:
        if p.exists():
            return p
    return None


def sync_opa_policy() -> bool:
    """Push the current Rego policy to OPA's policy API so a fresh API start always
    lands the right policy (OPA is no longer file-mounted). Eliminates the 'stale
    policy until OPA is manually recreated' class of problem."""
    path = _rego_path()
    if path is None:
        logger.warning("rego policy file not found; cannot push to OPA")
        return False
    url = f"{settings.opa_url}/v1/policies/aegis_authz"
    try:
        with httpx.Client(timeout=settings.opa_timeout_seconds) as client:
            resp = client.put(url, content=path.read_text().encode(), headers={"Content-Type": "text/plain"})
            resp.raise_for_status()
        logger.info("pushed Rego policy to OPA from %s", path)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("OPA policy push failed: %s", e)
        return False
