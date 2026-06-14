from __future__ import annotations

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from .auth import Subject
from .logging_config import get_logger, log_event
from .settings import settings
from .values import ResolvedValues

logger = get_logger("aegis.policy")


class PolicyDecision(BaseModel):
    allow: bool
    reasons: list[str] = []
    decision: str


async def decide(
    subject: Subject,
    action: str,
    resource: dict,
    values: ResolvedValues,
    runtime: dict | None = None,
) -> PolicyDecision:
    """Ask the PDP whether ``subject`` may perform ``action`` on ``resource``.

    The resource's *owning* tenant must be supplied by the caller (in
    ``resource['tenant_id']``) so the PDP can perform a real cross-tenant
    isolation check. If the caller omits it we fall back to the subject's
    tenant, but callers touching tenant-scoped data (memory, sessions) MUST
    pass the resource owner's tenant so the check is not tautological.
    """
    resource_tenant = resource.get("tenant_id", subject.tenant_id)
    payload = {
        "input": {
            "subject": {
                "email": subject.email,
                "tenant_id": subject.tenant_id,
                "team_id": subject.team_id,
                "role": subject.role,
                "groups": subject.groups,
            },
            "action": action,
            "resource": {**resource, "tenant_id": resource_tenant},
            "values": values.model_dump(),
            "runtime": runtime or {},
        }
    }
    url = f"{settings.opa_url}/v1/data/{settings.opa_package.replace('.', '/')}/result"
    try:
        async with httpx.AsyncClient(timeout=settings.opa_timeout_seconds) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            result = resp.json().get("result", None)
        if result is None:
            # The PDP answered but the queried document is undefined — treat as a
            # misconfiguration and fail closed rather than silently allowing.
            raise RuntimeError(
                f"PDP returned no '{settings.opa_package}.result' document; "
                "check that the policy bundle defines `result`."
            )
    except Exception as e:
        if settings.require_opa:
            log_event(logger, 40, "pdp_unreachable_fail_closed", action=action, error=str(e))
            raise HTTPException(status_code=503, detail=f"PDP unreachable; fail closed: {e}")
        log_event(logger, 30, "pdp_unreachable_using_fallback", action=action, error=str(e))
        result = _fallback(action, payload["input"]["resource"], values, subject)

    if isinstance(result, bool):
        allow, reasons = result, []
    else:
        allow = bool(result.get("allow"))
        reasons = result.get("reasons") or []
    return PolicyDecision(allow=allow, reasons=reasons, decision="allow" if allow else "deny")


def require(decision: PolicyDecision) -> None:
    if not decision.allow:
        raise HTTPException(status_code=403, detail={"decision": "deny", "reasons": decision.reasons})


def _valid_tenant(resource: dict, subject: Subject) -> bool:
    return bool(resource.get("tenant_id")) and resource.get("tenant_id") == subject.tenant_id


def _fallback(action, resource, values, subject) -> dict:
    """In-process default-deny policy used only when require_opa is false. Mirrors
    deploy/opa/aegis.rego and evaluates against the subject's resolved capabilities."""
    reasons: list[str] = []
    if not _valid_tenant(resource, subject):
        return {"allow": False, "reasons": ["missing_or_invalid_tenant_claim"]}
    allow = False
    if action == "skill.invoke":
        # Skills are open to every authenticated user; per-skill governance
        # happens via the actions the skill itself executes (memory.read,
        # tool.call, model.call) which remain role-gated.
        allow = bool(resource.get("skill_id"))
    elif action == "memory.read":
        # Memory reads are tenant-scoped at the SQL layer; within a tenant,
        # any authenticated user can read any namespace.
        allow = bool(resource.get("namespace"))
    elif action == "memory.write":
        # Writes also no longer require a per-role namespace grant within
        # the tenant; the classification ceiling is preserved.
        ns_ok = bool(resource.get("namespace"))
        cls = resource.get("classification")
        cls_ok = (cls is None) or (cls in values.writable_classifications)
        allow = ns_ok and cls_ok
        if ns_ok and not cls_ok:
            reasons.append(f"classification_above_max_write:{cls}")
    elif action == "tool.call":
        # Tools are open to every authenticated user, mirroring the skills
        # policy. Per-tool side-effects are still governed by egress rules.
        allow = bool(resource.get("tool_id"))
    elif action == "model.call":
        region_ok = resource.get("region") in values.allowed_model_regions
        prov = resource.get("provider")
        prov_ok = (not values.allowed_providers) or (prov in values.allowed_providers)
        allow = region_ok and prov_ok
        if region_ok and not prov_ok:
            reasons.append(f"provider_not_allowed:{prov}")
    elif action == "runtime.exec":
        allow = bool(values.runtime_exec) and resource.get("network") == "none"
    if not allow and not reasons:
        reasons.append(f"action_not_permitted:{action}")
    return {"allow": allow, "reasons": reasons}
