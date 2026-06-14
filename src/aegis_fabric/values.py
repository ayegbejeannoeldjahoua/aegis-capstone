from __future__ import annotations

from pydantic import BaseModel

from . import platform_settings, rbac
from .db import get_conn
from .logging_config import get_logger
from .rbac import role_capabilities
from .settings import settings

logger = get_logger("aegis.values")


class ResolvedValues(BaseModel):
    tenant_id: str
    team_id: str
    role: str
    user: str
    # capability-derived access controls
    skills: list[str] = []
    allowed_tools: list[str] = []
    readable_namespaces: list[str] = []
    writable_namespaces: list[str] = []
    allowed_model_regions: list[str] = ["AC1"]
    allowed_model_region: str = "AC1"
    runtime_exec: bool = False
    # data classification
    max_read_classification: str = "internal"
    max_write_classification: str = "internal"
    readable_classifications: list[str] = ["public", "internal"]
    writable_classifications: list[str] = ["public", "internal"]
    # model governance
    allowed_providers: list[str] = []
    allowed_model_ids: list[str] = []
    max_model_risk_tier: str = "T3"
    require_local_above_classification: str = "restricted"
    default_model: str | None = None  # platform-admin global model override (None -> registry default)
    # admin / governance RBAC
    admin_scope: str = "none"
    can_manage_users: bool = False
    can_manage_roles: bool = False
    can_edit_governance: bool = False
    can_register_skills: bool = False
    audit_scope: str = "own"
    # tool/skill governance (v1.6.0)
    allowed_model_purposes: list[str] = ["chat"]
    max_output_tokens: int = 1024
    max_tool_calls_per_request: int = 4
    egress_domains: list[str] = []
    pii_scope: str = "none"
    rate_limit_per_minute: int = 0
    daily_request_quota: int = 0
    token_budget_per_day: int = 0
    can_erase: bool = False
    erase_requires_approval: bool = True
    max_input_tokens: int = 8192
    fallback_mode: str = "degrade_local"
    residency_strict: bool = False
    runtime_max_seconds: int = 0
    runtime_memory_mb: int = 0
    runtime_network: str = "none"
    max_concurrent_requests: int = 0
    session_max_minutes: int = 0
    write_requires_approval_above: str = "restricted"
    # values cascade
    summary_words: int = 200
    org_invariants: dict = {"customer_data_boundary": "tenant", "outbound_region": "AC1"}
    policy_version: str = "policy-v1"
    values_version: str = "values-v1"
    # trace of cross-cutting VALUES that tightened the role-derived caps (org/team/individual)
    values_overlay: list[dict] = []


def _load_rules(tenant_id: str, team_id: str, role: str, user: str) -> dict:
    scopes = [("org", "org"), ("team", team_id), ("role", role), ("individual", user)]
    rules: dict[str, dict] = {}
    versions: dict[str, str] = {}
    try:
        with get_conn() as conn:
            for scope_type, scope_id in scopes:
                row = conn.execute(
                    "SELECT version, rules FROM values_rules WHERE tenant_id=%s AND scope_type=%s AND scope_id=%s "
                    "ORDER BY created_at DESC LIMIT 1",
                    (tenant_id, scope_type, scope_id),
                ).fetchone()
                if row:
                    rules[scope_type] = row["rules"]
                    versions[scope_type] = row["version"]
    except Exception as e:  # noqa: BLE001
        logger.warning("values_rules lookup failed, using defaults: %s", e)
    return {"rules": rules, "versions": versions}


_NUM_MIN_FIELDS = ("max_output_tokens", "max_input_tokens")
_QUOTA_MIN_FIELDS = ("token_budget_per_day", "daily_request_quota")  # 0 == unlimited
_CLASS_CEILING_FIELDS = ("max_read_classification", "max_write_classification",
                         "write_requires_approval_above")


def _apply_value_overlays(rv: "ResolvedValues", scoped: list[tuple[str, dict]]) -> None:
    """Cross-cutting governance: org/team/individual VALUES tighten (never widen) the
    role-derived capabilities. This is defense-in-depth -- a value can only make access more
    restrictive than the role's capabilities already allow, never grant more. The chain is
    org (broadest) -> team -> individual; because every rule below is "most restrictive wins"
    (min / lower-classification / logical-OR) the fold is order-independent. Each tightening is
    recorded in rv.values_overlay so the cascade is observable next to the capabilities."""
    trace: list[dict] = []

    def _tighten(field: str, scope: str, new) -> None:
        setattr(rv, field, new)
        trace.append({"scope": scope, "field": field, "value": new})

    for scope, block in scoped:
        if not block:
            continue
        # plain maxima -> smallest wins
        for f in _NUM_MIN_FIELDS:
            cand = block.get(f)
            if isinstance(cand, int) and cand > 0 and cand < getattr(rv, f):
                _tighten(f, scope, cand)
        # quotas where 0 means "unlimited" -> smallest positive wins
        for f in _QUOTA_MIN_FIELDS:
            cand = block.get(f)
            if isinstance(cand, int) and cand > 0:
                cur = getattr(rv, f)
                if cur == 0 or cand < cur:
                    _tighten(f, scope, cand)
        # classification ceilings/thresholds -> lower (more restrictive) classification wins
        for f in _CLASS_CEILING_FIELDS:
            cand = block.get(f)
            if cand and rbac.class_rank(cand) < rbac.class_rank(getattr(rv, f)):
                _tighten(f, scope, cand)
        # strict residency is one-way: any scope can turn it on
        if block.get("residency_strict") and not rv.residency_strict:
            _tighten("residency_strict", scope, True)

    # keep the derived read/write classification lists consistent with any tightened ceiling
    rv.readable_classifications = rbac.classes_up_to(rv.max_read_classification)
    rv.writable_classifications = rbac.classes_up_to(rv.max_write_classification)
    rv.values_overlay = trace


def resolve_values(
    tenant_id: str, team_id: str, role: str, user: str, requested_summary_words: int | None = None
) -> ResolvedValues:
    caps = role_capabilities(tenant_id, role)
    loaded = _load_rules(tenant_id, team_id, role, user)
    rules, versions = loaded["rules"], loaded["versions"]

    org = rules.get("org", {})
    team = rules.get("team", {})
    indiv = rules.get("individual", {})

    cap_max = caps.get("max_summary_words") or 200
    candidates = [
        org.get("max_summary_words", cap_max),
        team.get("default_summary_words", cap_max),
        indiv.get("preferred_summary_words", cap_max),
        cap_max,
    ]
    if requested_summary_words is not None:
        candidates.append(requested_summary_words)
    summary_words = max(1, min(candidates))

    regions = caps.get("allowed_model_regions") or [settings.model_region]
    org_invariants = org.get("org_invariants", {"customer_data_boundary": "tenant", "outbound_region": regions[0]})
    values_version = (
        f"{tenant_id}:org-{versions.get('org','na')}/team-{versions.get('team','na')}"
        f"/role-{versions.get('role','na')}/user-{versions.get('individual','na')}"
        if versions else f"{tenant_id}:role-{role}-caps"
    )

    rv = ResolvedValues(
        tenant_id=tenant_id, team_id=team_id, role=role, user=user,
        skills=caps["skills"], allowed_tools=caps["tools"],
        readable_namespaces=caps["readable_namespaces"], writable_namespaces=caps["writable_namespaces"],
        allowed_model_regions=regions, allowed_model_region=regions[0], runtime_exec=caps["runtime_exec"],
        max_read_classification=caps["max_read_classification"],
        max_write_classification=caps["max_write_classification"],
        readable_classifications=rbac.classes_up_to(caps["max_read_classification"]),
        writable_classifications=rbac.classes_up_to(caps["max_write_classification"]),
        allowed_providers=caps["allowed_providers"], allowed_model_ids=caps["allowed_model_ids"],
        max_model_risk_tier=caps["max_model_risk_tier"],
        require_local_above_classification=caps["require_local_above_classification"],
        default_model=platform_settings.get_default_model(),
        admin_scope=caps["admin_scope"], can_manage_users=caps["can_manage_users"],
        can_manage_roles=caps["can_manage_roles"], can_edit_governance=caps["can_edit_governance"],
        can_register_skills=caps["can_register_skills"], audit_scope=caps["audit_scope"],
        allowed_model_purposes=caps["allowed_model_purposes"], max_output_tokens=caps["max_output_tokens"],
        max_tool_calls_per_request=caps["max_tool_calls_per_request"], egress_domains=caps["egress_domains"],
        pii_scope=caps["pii_scope"],
        rate_limit_per_minute=caps["rate_limit_per_minute"], daily_request_quota=caps["daily_request_quota"],
        token_budget_per_day=caps["token_budget_per_day"],
        can_erase=caps["can_erase"], erase_requires_approval=caps["erase_requires_approval"],
        max_input_tokens=caps["max_input_tokens"], fallback_mode=caps["fallback_mode"],
        residency_strict=caps["residency_strict"], runtime_max_seconds=caps["runtime_max_seconds"],
        runtime_memory_mb=caps["runtime_memory_mb"], runtime_network=caps["runtime_network"],
        max_concurrent_requests=caps["max_concurrent_requests"], session_max_minutes=caps["session_max_minutes"],
        write_requires_approval_above=caps["write_requires_approval_above"],
        summary_words=summary_words, org_invariants=org_invariants, values_version=values_version,
    )
    _apply_value_overlays(rv, [("org", org), ("team", team), ("individual", indiv)])
    return rv
