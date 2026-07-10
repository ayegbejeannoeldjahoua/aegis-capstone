"""Administrative / governance-write API (guarded by require_admin).

Creating a tenant here gives it the *same shape* as the seeded tenants: teams,
roles instantiated from capability templates, an org-level values row, and an
immediate OPA re-sync so the new tenant is enforceable without any policy edit.
Every governance mutation is written to the audit ledger.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import approvals, export_state, keycloak_admin, platform_settings, rbac
from .audit import append_event
from .auth import get_subject, AdminPrincipal, Subject, admin_principal, require_cap, require_platform, scope_tenant
from .db import get_conn, run_db
from .models import registry as model_registry
from .values import resolve_values
from .logging_config import get_logger

logger = get_logger("aegis.admin")

router = APIRouter(prefix="/admin", tags=["admin"])

DEFAULT_TEAMS = ["research"]
DEFAULT_ROLE_TEMPLATES = ["analyst", "lead", "viewer"]
_TENANT_ID_RE = r"^[a-z0-9][a-z0-9-]{1,62}$"


class RoleSpec(BaseModel):
    role_id: str = Field(min_length=1, max_length=64)
    team_id: str = "research"
    template_id: str | None = None  # defaults to role_id
    capabilities: dict | None = None  # optional override of the template


class ConfirmDelete(BaseModel):
    confirm: str  # must equal the tenant_id being deleted


class TenantCreate(BaseModel):
    tenant_id: str = Field(pattern=_TENANT_ID_RE)
    display_name: str = Field(min_length=1, max_length=200)
    region: str = "AC1"
    teams: list[str] = Field(default_factory=lambda: list(DEFAULT_TEAMS))
    roles: list[RoleSpec] | None = None


def _audit_admin(action: str, resource: str, tenant_id: str, payload: dict) -> None:
    try:
        append_event(
            trace_id=uuid.uuid4().hex, span_id=None, parent_span_id=None,
            tenant_id=tenant_id, subject="platform-admin", action=action, resource=resource,
            policy_version="policy-v1", values_version="admin", decision="allow", reason=None, payload=payload,
        )
    except Exception as e:  # auditing must never break the operation, but we log loudly
        logger.warning("admin audit write failed for %s: %s", action, e)


def _create_tenant(payload: TenantCreate) -> dict:
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM tenants WHERE tenant_id=%s", (payload.tenant_id,)).fetchone():
            raise ValueError("tenant_exists")
        conn.execute(
            "INSERT INTO tenants(tenant_id, display_name, region) VALUES (%s,%s,%s)",
            (payload.tenant_id, payload.display_name, payload.region),
        )
        teams = payload.teams or list(DEFAULT_TEAMS)
        for tm in teams:
            conn.execute(
                "INSERT INTO teams(tenant_id, team_id, display_name) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (payload.tenant_id, tm, tm.replace("-", " ").title()),
            )
        # Org-level values so the cascade matches the seeded tenants.
        conn.execute(
            "INSERT INTO values_rules(tenant_id, scope_type, scope_id, version, rules) "
            "VALUES (%s,'org','org','org-v1',%s) ON CONFLICT DO NOTHING",
            (payload.tenant_id, json.dumps({
                "version": "org-v1", "allowed_model_region": payload.region,
                "org_invariants": {"customer_data_boundary": "tenant", "outbound_region": payload.region},
                "max_summary_words": 400,
            })),
        )
        specs = payload.roles
        if specs is None:
            first_team = teams[0] if teams else "research"
            specs = [RoleSpec(role_id=r, team_id=first_team, template_id=r) for r in DEFAULT_ROLE_TEMPLATES]
        created: list[dict] = []
        for r in specs:
            template_id = r.template_id or r.role_id
            caps = rbac.normalize_caps(r.capabilities) if r.capabilities else rbac.template_capabilities(template_id)
            conn.execute(
                "INSERT INTO roles(tenant_id, role_id, team_id, template_id, capabilities) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, role_id) DO UPDATE SET team_id=EXCLUDED.team_id, "
                "template_id=EXCLUDED.template_id, capabilities=EXCLUDED.capabilities",
                (payload.tenant_id, r.role_id, r.team_id, template_id, json.dumps(caps)),
            )
            created.append({"role_id": r.role_id, "team_id": r.team_id, "template_id": template_id, "capabilities": caps})
    # Provision the tenant's document database (best-effort; never blocks tenant creation).
    try:
        from .documents import document_store

        document_store.provision(payload.tenant_id)
    except Exception:  # noqa: BLE001
        pass
    # Enforceable immediately: push the updated capability map to OPA.
    rbac.sync_opa()
    _audit_admin("admin.tenant.create", payload.tenant_id, payload.tenant_id,
                 {"display_name": payload.display_name, "region": payload.region,
                  "teams": teams, "roles": [c["role_id"] for c in created]})
    logger.info("created tenant %s with roles %s", payload.tenant_id, [c["role_id"] for c in created])
    return {"tenant_id": payload.tenant_id, "display_name": payload.display_name,
            "region": payload.region, "teams": teams, "roles": created}


def _delete_tenant(tenant_id: str) -> dict:
    """Delete a tenant and its tenant-scoped data. teams/roles/memories/sessions/
    user_assignments cascade via FK; the audit ledger (audit_events, no FK) is RETAINED
    so the immutable, compliance-grade record of the tenant survives its deletion."""
    with get_conn() as conn:
        row = conn.execute("DELETE FROM tenants WHERE tenant_id=%s RETURNING tenant_id", (tenant_id,)).fetchone()
        if not row:
            raise ValueError("tenant_not_found")
    rbac.sync_opa()
    _audit_admin("admin.tenant.delete", tenant_id, tenant_id, {"cascade": "teams/roles/memories/sessions/assignments", "audit_retained": True})
    logger.info("deleted tenant %s (audit ledger retained)", tenant_id)
    return {"ok": True, "deleted": tenant_id}


def _list_tenants() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT t.tenant_id, t.display_name, t.region, "
            "(SELECT count(*) FROM roles r WHERE r.tenant_id=t.tenant_id) AS role_count "
            "FROM tenants t ORDER BY t.tenant_id"
        ).fetchall()
    return [dict(r) for r in rows]


def _get_tenant(tenant_id: str) -> dict | None:
    with get_conn() as conn:
        t = conn.execute(
            "SELECT tenant_id, display_name, region FROM tenants WHERE tenant_id=%s", (tenant_id,)
        ).fetchone()
        if not t:
            return None
        teams = conn.execute(
            "SELECT team_id, display_name FROM teams WHERE tenant_id=%s ORDER BY team_id", (tenant_id,)
        ).fetchall()
        roles = conn.execute(
            "SELECT role_id, team_id, template_id, capabilities FROM roles WHERE tenant_id=%s ORDER BY role_id",
            (tenant_id,),
        ).fetchall()
    out = dict(t)
    out["teams"] = [dict(x) for x in teams]
    out["roles"] = [dict(x) for x in roles]
    return out


def _list_templates() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT template_id, display_name, capabilities FROM role_templates ORDER BY template_id"
        ).fetchall()
    if rows:
        return [dict(r) for r in rows]
    # Fall back to the built-in catalog if templates aren't seeded yet.
    return [{"template_id": k, "display_name": v["display_name"], "capabilities": rbac.normalize_caps(v["capabilities"])}
            for k, v in rbac.DEFAULT_TEMPLATES.items()]


@router.post("/tenants", status_code=201)
async def create_tenant(payload: TenantCreate, principal: AdminPrincipal = Depends(admin_principal)):
    require_platform(principal)
    try:
        return await run_db(_create_tenant, payload)
    except ValueError as e:
        if str(e) == "tenant_exists":
            raise HTTPException(status_code=409, detail=f"tenant '{payload.tenant_id}' already exists")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tenants")
async def list_tenants(principal: AdminPrincipal = Depends(admin_principal)):
    tenants = await run_db(_list_tenants)
    if principal.scope == "tenant":
        tenants = [t for t in tenants if t["tenant_id"] == principal.tenant_id]
    return {"tenants": tenants}


@router.get("/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, tenant_id)
    t = await run_db(_get_tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="tenant not found")
    return t


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, payload: ConfirmDelete, principal: AdminPrincipal = Depends(admin_principal)):
    require_platform(principal)
    require_cap(principal, "can_delete_tenant")
    if payload.confirm != tenant_id:
        raise HTTPException(status_code=400, detail="confirm must equal the tenant_id")
    if "tenant.delete" in (principal.dual_control_actions or []):
        # dual control: queue for a second approver instead of deleting now
        return await run_db(approvals.create_pending, tenant_id, "tenant.delete",
                            {"tenant_id": tenant_id}, principal.email, "tenant deletion")
    try:
        return await run_db(_delete_tenant, tenant_id)
    except ValueError as e:
        _value_err(e)


@router.get("/templates")
async def list_templates(principal: AdminPrincipal = Depends(admin_principal)):
    return {"templates": await run_db(_list_templates)}


@router.get("/skills")
async def admin_list_skills(principal: AdminPrincipal = Depends(admin_principal)):
    from .skills import skill_registry

    return {"skills": skill_registry.catalog()}


@router.get("/tools")
async def admin_list_tools(principal: AdminPrincipal = Depends(admin_principal)):
    from . import tools as toolmod

    return {"tools": toolmod.catalog()}


@router.get("/vocab")
async def admin_vocab(principal: AdminPrincipal = Depends(admin_principal)):
    from .vocab import governance_vocab

    return governance_vocab()


@router.get("/traces")
async def admin_traces(limit: int = 20, principal: AdminPrincipal = Depends(admin_principal)):
    require_cap(principal, "can_view_traces")
    from .audit import recent_traces

    scope = "all" if principal.scope == "platform" else "tenant"
    return {"traces": await run_db(recent_traces, principal.tenant_id, scope, limit)}


@router.get("/signing-keys")
async def admin_signing_keys(principal: AdminPrincipal = Depends(admin_principal)):
    require_cap(principal, "can_manage_signing_keys")
    from .settings import settings as st

    return {"algorithm": "ed25519", "public_key": st.skill_public_key, "require_signature": st.require_skill_signature}


@router.post("/secrets/rotate")
async def admin_rotate_secret(payload: SecretRotate, principal: AdminPrincipal = Depends(admin_principal)):
    require_cap(principal, "can_rotate_secrets")
    if "secret.rotate" in (principal.dual_control_actions or []):
        return await run_db(approvals.create_pending, (principal.tenant_id or "platform"), "secret.rotate",
                            {"name": payload.name}, principal.email, "secret rotation")
    return await run_db(_rotate_secret, payload.name)


@router.post("/skills/register")
async def admin_register_skill(payload: SkillRegister, principal: AdminPrincipal = Depends(admin_principal)):
    require_cap(principal, "can_register_skills")
    from .signing import verify

    signed = verify(payload.manifest)
    sid = payload.manifest.get("skill_id")
    _audit_admin("admin.skill.register", sid or "?", principal.tenant_id or "*", {"signature_valid": signed})
    return {"skill_id": sid, "signature_valid": signed, "accepted": bool(signed and sid),
            "note": "signature validated; persistence to the skill registry is a deploy-time step"}


@router.post("/impersonate")
async def admin_impersonate(payload: Impersonate, principal: AdminPrincipal = Depends(admin_principal)):
    if principal.can_impersonate == "none":
        raise HTTPException(status_code=403, detail="missing capability: can_impersonate")
    tf = principal.tenant_id if principal.scope == "tenant" else None
    try:
        return await run_db(_impersonate_context, payload.email, tf)
    except ValueError as e:
        _value_err(e)


@router.post("/tenants/{tenant_id}/docs/seed")
async def seed_tenant_docs(tenant_id: str, principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, tenant_id)
    require_cap(principal, "can_edit_governance")
    return await run_db(_seed_docs, tenant_id)


@router.get("/tenants/{tenant_id}/docs")
async def tenant_docs_count(tenant_id: str, principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, tenant_id)
    from .documents import document_store

    return {"tenant_id": tenant_id, "count": await run_db(document_store.count, tenant_id)}


@router.get("/audit/last")
async def admin_audit_last(
    limit: int = 50,
    month: str | None = None,
    principal: AdminPrincipal = Depends(admin_principal),
):
    """The audit ledger, filtered by the caller's audit_scope (platform/all = whole ledger)."""
    from .audit import last

    return {
        "events": await run_db(last, principal.tenant_id, principal.audit_scope, principal.email, limit, month),
        "scope": principal.audit_scope,
        "month": month,
    }


@router.get("/audit/trace/{trace_id}")
async def admin_audit_trace(trace_id: str, principal: AdminPrincipal = Depends(admin_principal)):
    from .audit import trace

    return {"trace_id": trace_id,
            "events": await run_db(trace, trace_id, principal.tenant_id, principal.audit_scope, principal.email)}


@router.get("/audit/verify")
async def admin_audit_verify(principal: AdminPrincipal = Depends(admin_principal)):
    require_cap(principal, "can_view_traces")
    from .audit import verify_chain

    return await run_db(verify_chain)


def _approval_err(e: ValueError):
    codes = {"approval_not_found": 404, "approval_not_pending": 409, "self_approval_forbidden": 403,
             "approval_expired": 410, "no_executor_for_action": 400}
    raise HTTPException(status_code=codes.get(str(e), 400), detail=str(e))


@router.get("/approvals")
async def list_approvals(principal: AdminPrincipal = Depends(admin_principal)):
    if principal.can_approve == "none" and principal.scope != "platform":
        raise HTTPException(status_code=403, detail="no approval capability")
    tf = principal.tenant_id if principal.scope == "tenant" else None
    return {"approvals": await run_db(approvals.list_pending, tf)}


@router.post("/approvals/{pending_id}/approve")
async def approve_action(pending_id: int, principal: AdminPrincipal = Depends(admin_principal)):
    if principal.can_approve == "none":
        raise HTTPException(status_code=403, detail="this role cannot approve")
    tf = principal.tenant_id if principal.scope == "tenant" else None
    try:
        return await run_db(approvals.approve, pending_id, principal.email, tf)
    except ValueError as e:
        _approval_err(e)


@router.post("/approvals/{pending_id}/reject")
async def reject_action(pending_id: int, principal: AdminPrincipal = Depends(admin_principal)):
    if principal.can_approve == "none":
        raise HTTPException(status_code=403, detail="this role cannot approve")
    tf = principal.tenant_id if principal.scope == "tenant" else None
    try:
        return await run_db(approvals.reject, pending_id, principal.email, tf)
    except ValueError as e:
        _approval_err(e)


# ===========================================================================
# Slice #12 — roles from templates ; #13 — governance edits ; #14 — users
# ===========================================================================

class RoleCreate(BaseModel):
    role_id: str = Field(min_length=1, max_length=64)
    team_id: str = "research"
    template_id: str | None = None
    capabilities: dict | None = None


class CapabilitiesUpdate(BaseModel):
    capabilities: dict


class TemplateUpsert(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    capabilities: dict


class AssignmentCreate(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    tenant_id: str
    team_id: str = "research"
    role_id: str
    create_login: bool = False
    password: str | None = None


class PasswordReset(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class DefaultModel(BaseModel):
    model_id: str = Field(min_length=1, max_length=200)


class ProvisionLogin(BaseModel):
    """(Re)provision a Keycloak login for an *existing* assignment.

    A Keycloak reset (dev H2) wipes runtime-created logins and re-issues new
    ``sub`` values, leaving Postgres assignments stranded (orphaned login +
    stale binding). This makes recovery a one-click admin action: it creates
    the login if missing and sets ``password`` so the account is immediately
    usable, and (by default) clears the stale ``sub`` binding so the fresh
    login re-binds on next sign-in."""
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    rebind: bool = True


class TeamCreate(BaseModel):
    team_id: str = Field(pattern=_TENANT_ID_RE)
    display_name: str | None = None


class SecretRotate(BaseModel):
    name: str = Field(default="demo-secret", max_length=120)


class SkillRegister(BaseModel):
    manifest: dict


class Impersonate(BaseModel):
    email: str = Field(min_length=3, max_length=200)


class AssignmentUpdate(BaseModel):
    """Partial move/edit of an existing assignment. Omitted fields are unchanged.
    The sub binding is preserved, so the change takes effect on the next request
    with no re-login."""
    tenant_id: str | None = None
    team_id: str | None = None
    role_id: str | None = None


# ---- role management (#12) ------------------------------------------------
def _add_role(tenant_id: str, r: RoleCreate) -> dict:
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM tenants WHERE tenant_id=%s", (tenant_id,)).fetchone():
            raise ValueError("tenant_not_found")
        if conn.execute("SELECT 1 FROM roles WHERE tenant_id=%s AND role_id=%s", (tenant_id, r.role_id)).fetchone():
            raise ValueError("role_exists")
        template_id = r.template_id or r.role_id
        caps = rbac.normalize_caps(r.capabilities) if r.capabilities else rbac.template_capabilities(template_id)
        conn.execute(
            "INSERT INTO roles(tenant_id, role_id, team_id, template_id, capabilities) VALUES (%s,%s,%s,%s,%s)",
            (tenant_id, r.role_id, r.team_id, template_id, json.dumps(caps)),
        )
    rbac.sync_opa()
    _audit_admin("admin.role.create", f"{tenant_id}/{r.role_id}", tenant_id, {"template_id": template_id, "capabilities": caps})
    return {"tenant_id": tenant_id, "role_id": r.role_id, "team_id": r.team_id, "template_id": template_id, "capabilities": caps}


def _delete_role(tenant_id: str, role_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("DELETE FROM roles WHERE tenant_id=%s AND role_id=%s RETURNING role_id", (tenant_id, role_id)).fetchone()
        if not row:
            raise ValueError("role_not_found")
    rbac.sync_opa()
    _audit_admin("admin.role.delete", f"{tenant_id}/{role_id}", tenant_id, {})
    return {"ok": True, "deleted": role_id}


# ---- governance edits (#13) -----------------------------------------------
def _update_role_caps(tenant_id: str, role_id: str, caps: dict) -> dict:
    norm = rbac.normalize_caps(caps)
    with get_conn() as conn:
        row = conn.execute(
            "UPDATE roles SET capabilities=%s WHERE tenant_id=%s AND role_id=%s RETURNING role_id",
            (json.dumps(norm), tenant_id, role_id),
        ).fetchone()
        if not row:
            raise ValueError("role_not_found")
    rbac.sync_opa()
    _audit_admin("admin.role.update_capabilities", f"{tenant_id}/{role_id}", tenant_id, {"capabilities": norm})
    return {"tenant_id": tenant_id, "role_id": role_id, "capabilities": norm}


def _upsert_template(template_id: str, t: TemplateUpsert) -> dict:
    norm = rbac.normalize_caps(t.capabilities)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO role_templates(template_id, display_name, capabilities) VALUES (%s,%s,%s) "
            "ON CONFLICT (template_id) DO UPDATE SET display_name=EXCLUDED.display_name, capabilities=EXCLUDED.capabilities",
            (template_id, t.display_name, json.dumps(norm)),
        )
    _audit_admin("admin.template.upsert", template_id, "*", {"capabilities": norm})
    return {"template_id": template_id, "display_name": t.display_name, "capabilities": norm}


# ---- users / assignments (#14) --------------------------------------------
def _list_assignments() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT assignment_id, user_email, tenant_id, team_id, role_id, (sub IS NOT NULL) AS bound "
            "FROM user_assignments ORDER BY tenant_id, user_email"
        ).fetchall()
    return [dict(r) for r in rows]


def _create_assignment(a: AssignmentCreate) -> dict:
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM roles WHERE tenant_id=%s AND role_id=%s", (a.tenant_id, a.role_id)).fetchone():
            raise ValueError("role_not_found")
        if conn.execute(
            "SELECT 1 FROM user_assignments WHERE lower(user_email)=lower(%s) AND tenant_id=%s",
            (a.email, a.tenant_id),
        ).fetchone():
            raise ValueError("assignment_exists")
        conn.execute(
            "INSERT INTO user_assignments(user_email, tenant_id, team_id, role_id) VALUES (%s,%s,%s,%s)",
            (a.email, a.tenant_id, a.team_id, a.role_id),
        )
    login = None
    if a.create_login:
        if not a.password:
            raise ValueError("password_required_for_login")
        login = keycloak_admin.create_login(a.email, a.password)
    _audit_admin("admin.assignment.create", a.email, a.tenant_id,
                 {"role_id": a.role_id, "team_id": a.team_id, "login_created": bool(login and login.get("created"))})
    return {"email": a.email, "tenant_id": a.tenant_id, "team_id": a.team_id, "role_id": a.role_id, "login": login}


def _delete_assignment(assignment_id: int, tenant_filter: str | None = None) -> dict:
    sql = "DELETE FROM user_assignments WHERE assignment_id=%s"
    params = [assignment_id]
    if tenant_filter:
        sql += " AND tenant_id=%s"
        params.append(tenant_filter)
    with get_conn() as conn:
        row = conn.execute(sql + " RETURNING user_email, tenant_id", params).fetchone()
        if not row:
            raise ValueError("assignment_not_found")
    _audit_admin("admin.assignment.delete", row["user_email"], row["tenant_id"], {})
    return {"ok": True, "deleted": assignment_id}


def _reset_user_password(p: "PasswordReset", tenant_filter: str | None) -> dict:
    """Admin-initiated reset of an *existing* login's password. Confined to the
    admin's tenant when tenant-scoped; platform admins may reset any. Requires the
    email to have an assignment in scope, and a Keycloak login to actually exist."""
    with get_conn() as conn:
        sql = "SELECT 1 FROM user_assignments WHERE lower(user_email)=lower(%s)"
        params: list = [p.email]
        if tenant_filter:
            sql += " AND tenant_id=%s"
            params.append(tenant_filter)
        if not conn.execute(sql, params).fetchone():
            raise ValueError("assignment_not_found")
    res = keycloak_admin.set_password_by_username(p.email, p.new_password)
    _audit_admin("admin.user.reset_password", p.email, tenant_filter or "*",
                 {"login_updated": bool(res.get("updated"))})
    return {"email": p.email, **res}


def _provision_login(p: "ProvisionLogin", tenant_filter: str | None) -> dict:
    """(Re)create or refresh a Keycloak login for an existing assignment.

    Requires the email to have an assignment in scope (tenant-scoped admins are
    confined to their tenant). Creates the Keycloak login if missing and always
    sets the supplied password so the account is usable regardless of prior
    state; when ``rebind`` is set (default) it clears the stale sub-binding so
    the freshly-provisioned login binds on the next authenticated request."""
    with get_conn() as conn:
        sql = "SELECT assignment_id FROM user_assignments WHERE lower(user_email)=lower(%s)"
        params: list = [p.email]
        if tenant_filter:
            sql += " AND tenant_id=%s"
            params.append(tenant_filter)
        rows = conn.execute(sql, params).fetchall()
        if not rows:
            raise ValueError("assignment_not_found")
        rebound = 0
        if p.rebind:
            rsql = "UPDATE user_assignments SET sub=NULL, bound_at=NULL WHERE lower(user_email)=lower(%s)"
            rparams: list = [p.email]
            if tenant_filter:
                rsql += " AND tenant_id=%s"
                rparams.append(tenant_filter)
            conn.execute(rsql, rparams)
            rebound = len(rows)
    login = keycloak_admin.create_login(p.email, p.password)
    if not login.get("created"):
        # Login already existed (or provisioning disabled): ensure the supplied
        # password actually works so the account is usable regardless of state.
        try:
            pw = keycloak_admin.set_password_by_username(p.email, p.password)
            login = {**login, "password_set": bool(pw.get("updated"))}
        except ValueError:
            pass  # login_not_found (e.g. provisioning disabled) -- nothing to set
    _audit_admin("admin.user.provision_login", p.email, tenant_filter or "*",
                 {"login_created": bool(login.get("created")), "rebound": rebound})
    return {"email": p.email, "rebound": rebound, "login": login}


def _add_team(tenant_id: str, t: TeamCreate) -> dict:
    display = t.display_name or t.team_id.replace("-", " ").title()
    with get_conn() as conn:
        if not conn.execute("SELECT 1 FROM tenants WHERE tenant_id=%s", (tenant_id,)).fetchone():
            raise ValueError("tenant_not_found")
        if conn.execute("SELECT 1 FROM teams WHERE tenant_id=%s AND team_id=%s", (tenant_id, t.team_id)).fetchone():
            raise ValueError("team_exists")
        conn.execute("INSERT INTO teams(tenant_id, team_id, display_name) VALUES (%s,%s,%s)",
                     (tenant_id, t.team_id, display))
    _audit_admin("admin.team.create", f"{tenant_id}/{t.team_id}", tenant_id, {"display_name": display})
    return {"tenant_id": tenant_id, "team_id": t.team_id, "display_name": display}


def _delete_team(tenant_id: str, team_id: str) -> dict:
    """Remove a team. Refuses if roles still reference it (move/delete them first),
    so we never orphan a role's team_id."""
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM roles WHERE tenant_id=%s AND team_id=%s", (tenant_id, team_id)).fetchone():
            raise ValueError("team_in_use")
        row = conn.execute("DELETE FROM teams WHERE tenant_id=%s AND team_id=%s RETURNING team_id",
                           (tenant_id, team_id)).fetchone()
        if not row:
            raise ValueError("team_not_found")
    _audit_admin("admin.team.delete", f"{tenant_id}/{team_id}", tenant_id, {})
    return {"ok": True, "deleted": team_id}


def _update_assignment(assignment_id: int, u: AssignmentUpdate, tenant_filter: str | None) -> dict:
    """Move/edit a single assignment in place (preserves sub). Validates the target
    role exists in the target tenant. tenant_filter (set for tenant-scoped admins)
    confines both the source row and the destination tenant to that tenant."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT assignment_id, user_email, tenant_id, team_id, role_id FROM user_assignments WHERE assignment_id=%s",
            (assignment_id,),
        ).fetchone()
        if not cur:
            raise ValueError("assignment_not_found")
        cur = dict(cur)
        if tenant_filter and cur["tenant_id"] != tenant_filter:
            raise ValueError("assignment_not_found")
        new_tenant = u.tenant_id or cur["tenant_id"]
        new_team = u.team_id or cur["team_id"]
        new_role = u.role_id or cur["role_id"]
        if tenant_filter and new_tenant != tenant_filter:
            raise ValueError("cross_tenant_move_forbidden")
        if not conn.execute("SELECT 1 FROM roles WHERE tenant_id=%s AND role_id=%s", (new_tenant, new_role)).fetchone():
            raise ValueError("role_not_found")
        conn.execute(
            "UPDATE user_assignments SET tenant_id=%s, team_id=%s, role_id=%s WHERE assignment_id=%s",
            (new_tenant, new_team, new_role, assignment_id),
        )
    _audit_admin("admin.assignment.update", cur["user_email"], new_tenant,
                 {"from": {"tenant_id": cur["tenant_id"], "team_id": cur["team_id"], "role_id": cur["role_id"]},
                  "to": {"tenant_id": new_tenant, "team_id": new_team, "role_id": new_role}})
    return {"assignment_id": assignment_id, "user_email": cur["user_email"],
            "tenant_id": new_tenant, "team_id": new_team, "role_id": new_role}


def _rotate_secret(name: str) -> dict:
    from .settings import generate_secret

    val = generate_secret()
    _audit_admin("admin.secret.rotate", name, "*", {"rotated": True})
    return {"rotated": True, "name": name, "new_value_preview": val[:6] + "\u2026",
            "note": "demo rotation \u2014 value is not persisted; wire to Vault/KMS for production"}


def _impersonate_context(email: str, tenant_filter: str | None) -> dict:
    with get_conn() as conn:
        sql = "SELECT tenant_id, team_id, role_id FROM user_assignments WHERE lower(user_email)=lower(%s)"
        params: list = [email]
        if tenant_filter:
            sql += " AND tenant_id=%s"
            params.append(tenant_filter)
        row = conn.execute(sql + " ORDER BY assignment_id LIMIT 1", params).fetchone()
    if not row:
        raise ValueError("assignment_not_found")
    caps = rbac.role_capabilities(row["tenant_id"], row["role_id"])
    return {"email": email, "tenant_id": row["tenant_id"], "team_id": row["team_id"], "role_id": row["role_id"],
            "capabilities": caps, "note": "read-only governance preview; no session is issued"}


def _seed_docs(tenant_id: str) -> dict:
    from .documents import default_corpus, document_store

    with get_conn() as conn:
        teams = [r["team_id"] for r in conn.execute(
            "SELECT team_id FROM teams WHERE tenant_id=%s ORDER BY team_id", (tenant_id,)).fetchall()]
        if not teams:
            teams = [r["team_id"] for r in conn.execute(
                "SELECT DISTINCT team_id FROM roles WHERE tenant_id=%s ORDER BY team_id", (tenant_id,)).fetchall()]
    document_store.provision(tenant_id)
    n = document_store.seed(tenant_id, default_corpus(tenant_id, teams))
    _audit_admin("admin.docs.seed", tenant_id, tenant_id, {"teams": teams, "docs": n})
    return {"tenant_id": tenant_id, "teams": teams, "seeded": n}


# ---- platform model selection (global default) ----------------------------
def _model_view() -> dict:
    """Active global model + the registry catalogue. Model risk-tier gating was removed in
    v1.15.0 ("no tiers in model use"): every registered model can serve every role and can be
    set as the global default. ``max_risk_tier`` is retained for display only. Per-role
    governance (classification, skills, tools, budgets) still applies on top."""
    selected = platform_settings.get_default_model()
    effective = selected or model_registry.default_model_id()
    models = model_registry.catalog()
    for m in models:
        tiers = m.get("risk_tiers") or []
        m["max_risk_tier"] = max(tiers, key=rbac.risk_rank) if tiers else "T1"
        m["serves_everyone"] = True
        m["active"] = m["model_id"] == effective
    return {"active_model": effective, "selected": selected,
            "source": "platform" if selected else "registry", "models": models}

def _set_default_model(p: "DefaultModel", actor: str) -> dict:
    mid = p.model_id
    if not model_registry.is_known(mid):
        raise ValueError("unknown_model")
    platform_settings.set_default_model(mid, actor)
    _audit_admin("admin.model.set_default", mid, "*", {"model_id": mid})
    return _model_view()


# ---- cross-cutting VALUES (org/team/role/individual) ----------------------------
# Demo values illustrate the cascade: org is the broadest cross-cutting layer, team narrows it.
# These are "most restrictive wins" knobs applied ON TOP of role capabilities (see values.py).
_DEMO_ORG_VALUES = {
    "max_summary_words": 400, "max_output_tokens": 2048,
    "max_read_classification": "confidential", "write_requires_approval_above": "internal",
    "token_budget_per_day": 500000, "residency_strict": False,
}
_DEMO_TEAM_VALUES = {
    "default_summary_words": 200, "max_output_tokens": 1024,
    "daily_request_quota": 2000, "write_requires_approval_above": "internal",
}


def _values_view(tenant_id: str) -> dict:
    """Every values_rules row for a tenant (latest version per scope), grouped by level so the
    console can show which values are defined at org / team / role / individual."""
    out: dict = {"tenant_id": tenant_id, "org": None, "teams": [], "roles": [], "individual": []}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ON (scope_type, scope_id) scope_type, scope_id, version, rules "
            "FROM values_rules WHERE tenant_id=%s ORDER BY scope_type, scope_id, created_at DESC",
            (tenant_id,),
        ).fetchall()
    for r in rows:
        item = {"scope_id": r["scope_id"], "version": r["version"], "rules": r["rules"]}
        bucket = {"org": "org", "team": "teams", "role": "roles", "individual": "individual"}.get(r["scope_type"])
        if bucket == "org":
            out["org"] = item
        elif bucket:
            out[bucket].append(item)
    return out


def _effective_values(tenant_id: str, team: str, role: str, user: str) -> dict:
    """Resolve capabilities + the values cascade for one (team, role, user) so the console can
    show the EFFECTIVE governance and exactly which values tightened which capability."""
    rv = resolve_values(tenant_id, team, role, user)
    d = rv.model_dump()
    return {"tenant_id": tenant_id, "team_id": team, "role": role, "user": user,
            "resolved": d, "values_overlay": d.get("values_overlay", [])}


_CAPABILITY_MATRIX_ACTIONS = [
    {
        "action": "memory.read",
        "category": "Memory",
        "label": "Read memory",
        "description": "Tenant-scoped retrieval from governed document memory.",
    },
    {
        "action": "memory.write",
        "category": "Memory",
        "label": "Write memory",
        "description": "Create or update tenant memory within classification and approval limits.",
    },
    {
        "action": "values.read",
        "category": "Values",
        "label": "Read values",
        "description": "Read role plus org/team/individual values that narrow capabilities.",
    },
    {
        "action": "values.write.own",
        "category": "Values",
        "label": "Edit own values",
        "description": "Set individual preferences that can only tighten effective behavior.",
    },
    {
        "action": "values.write.role",
        "category": "Values",
        "label": "Edit role values",
        "description": "Manage role-level values overlays for a governed tenant.",
    },
    {
        "action": "values.write.team",
        "category": "Values",
        "label": "Edit team values",
        "description": "Manage team-level values overlays for a governed tenant.",
    },
    {
        "action": "values.write.department",
        "category": "Values",
        "label": "Edit department values",
        "description": "Manage department-scoped values where the deployment has that scope.",
    },
    {
        "action": "values.write.organization",
        "category": "Values",
        "label": "Edit org values",
        "description": "Manage organization-wide invariants and values overlays.",
    },
    {
        "action": "model.call",
        "category": "Model",
        "label": "Call model",
        "description": "Invoke an allowed provider/model under region, purpose, and budget controls.",
    },
    {
        "action": "model.route",
        "category": "Model",
        "label": "Route model",
        "description": "Select an approved provider/model route for the request context.",
    },
    {
        "action": "tool.call",
        "category": "Tools",
        "label": "Call tool",
        "description": "Invoke an allowed tool with per-request and downstream governance checks.",
    },
    {
        "action": "egress.http",
        "category": "Egress",
        "label": "HTTP egress",
        "description": "Send data outside the tenant boundary to approved destinations only.",
    },
    {
        "action": "audit.read.own",
        "category": "Audit",
        "label": "Own audit",
        "description": "Read audit events for the user's own activity.",
    },
    {
        "action": "audit.read.tenant",
        "category": "Audit",
        "label": "Tenant audit",
        "description": "Read tenant-scoped audit and trace evidence.",
    },
    {
        "action": "audit.read.platform",
        "category": "Audit",
        "label": "Platform audit",
        "description": "Read platform-wide audit and trace evidence.",
    },
    {
        "action": "finops.read",
        "category": "FinOps",
        "label": "Read FinOps",
        "description": "View spend, usage, and budget telemetry for the admin scope.",
    },
    {
        "action": "policy.read",
        "category": "Policy",
        "label": "Read policy",
        "description": "Inspect role templates, values, and governance state.",
    },
    {
        "action": "policy.write",
        "category": "Policy",
        "label": "Write policy",
        "description": "Edit governance templates, values, and platform policy settings.",
    },
    {
        "action": "user.admin",
        "category": "Admin",
        "label": "User admin",
        "description": "Manage user assignments inside the authorized admin scope.",
    },
    {
        "action": "tenant.admin",
        "category": "Admin",
        "label": "Tenant admin",
        "description": "Manage tenant configuration or platform tenant lifecycle.",
    },
    {
        "action": "approval.review",
        "category": "Admin",
        "label": "Review approvals",
        "description": "Approve or reject pending dual-control actions.",
    },
    {
        "action": "runtime.invoke",
        "category": "Runtime",
        "label": "Invoke runtime",
        "description": "Use a governed runtime sandbox when the role allows execution.",
    },
    {
        "action": "runtime.python",
        "category": "Runtime",
        "label": "Python runtime",
        "description": "Run Python inside the runtime sandbox with duration, memory, and network controls.",
    },
    {
        "action": "cross_tenant.read",
        "category": "Tenant Boundary",
        "label": "Cross-tenant read",
        "description": "Read data from another tenant. Default is deny.",
    },
]

_CAPABILITY_MATRIX_PERSONAS = [
    {
        "email": "jane@acmecp.example",
        "tenant_id": "acmecp",
        "team_id": "research",
        "role_id": "analyst",
        "label": "Jane, Acme analyst",
    },
    {
        "email": "kim@acmecp.example",
        "tenant_id": "acmecp",
        "team_id": "research",
        "role_id": "lead",
        "label": "Kim, Acme lead",
    },
    {
        "email": "pat@acmecp.example",
        "tenant_id": "acmecp",
        "team_id": "research",
        "role_id": "tenant-admin",
        "label": "Pat, Acme tenant admin",
    },
    {
        "email": "priya@it.example",
        "tenant_id": "it",
        "team_id": "platform",
        "role_id": "platform-admin",
        "label": "Priya, platform admin",
    },
    {
        "email": "jane@finsvc.example",
        "tenant_id": "finsvc",
        "team_id": "research",
        "role_id": "analyst",
        "label": "Jane, FinSvc analyst",
    },
]

_CAPABILITY_MATRIX_SCENARIOS = [
    {
        "id": "s6_masked_transcript",
        "label": "S6 Jane transcript",
        "persona": "jane@acmecp.example",
        "actions": ["memory.read", "model.call"],
        "expected": "allowed tenant read with masked PII.",
    },
    {
        "id": "s7_full_pii_transcript",
        "label": "S7 Kim transcript",
        "persona": "kim@acmecp.example",
        "actions": ["memory.read", "model.call"],
        "expected": "allowed tenant read with full PII scope.",
    },
    {
        "id": "s10_values_write",
        "label": "S10 values governance",
        "persona": "pat@acmecp.example",
        "actions": ["values.write.team", "values.write.role", "policy.write"],
        "expected": "tenant-scoped governance edits only.",
    },
    {
        "id": "s16_prompt_injection",
        "label": "S16 prompt-injection inspection",
        "persona": "jane@acmecp.example",
        "actions": ["memory.read", "audit.read.own"],
        "expected": "canary evidence is treated as untrusted content.",
    },
]


def _row_dict(row) -> dict:
    return dict(row) if row is not None else {}


def _jsonish(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


def _caps_from(raw) -> dict:
    return rbac.normalize_caps(_jsonish(raw))


def _listish(raw) -> list:
    return raw if isinstance(raw, list) else []


def _textish(raw, fallback: str = "none") -> str:
    return str(raw) if raw not in (None, "") else fallback


def _decision(role_id: str, caps: dict, action: str) -> dict:
    admin_scope = _textish(caps.get("admin_scope"), "none")
    audit_scope = _textish(caps.get("audit_scope"), "none")
    egress = _listish(caps.get("egress_domains"))
    allowed_langs = _listish(caps.get("allowed_runtime_languages"))

    def out(decision: str, scope: str, reason: str, conditions: list[str] | None = None,
            evidence: list[str] | None = None) -> dict:
        return {
            "role_id": role_id,
            "action": action,
            "decision": decision,
            "scope": scope,
            "reason": reason,
            "conditions": conditions or [],
            "evidence_source": evidence or ["role_capabilities", "policy.pdp"],
            "scenario_ids": [s["id"] for s in _CAPABILITY_MATRIX_SCENARIOS if action in s["actions"]],
        }

    if action == "memory.read":
        return out(
            "conditional",
            "own_tenant",
            "Memory retrieval is tenant-scoped and capped by role classification limits.",
            [
                "resource.tenant_id must equal subject.tenant_id",
                f"classification must be <= {caps.get('max_read_classification')}",
                "retrieval SQL is tenant-filtered",
            ],
            ["policy.memory.read", "rbac.role_capabilities", "memory.sql_tenant_filter"],
        )
    if action == "memory.write":
        return out(
            "conditional",
            "own_tenant",
            "Writes are tenant-scoped and capped by writable classification and approval rules.",
            [
                f"classification must be <= {caps.get('max_write_classification')}",
                f"approval required above {caps.get('write_requires_approval_above')}",
                "namespace must be writable for the tenant role",
            ],
            ["policy.memory.write", "rbac.role_capabilities", "approvals"],
        )
    if action == "values.read":
        return out(
            "allow",
            "applicable_scope",
            "Resolved values are readable for the subject context so effective governance is explainable.",
            ["org/team/role/individual values are resolved from broadest to narrowest"],
            ["values.resolve_values", "rbac.role_capabilities"],
        )
    if action == "values.write.own":
        return out(
            "conditional",
            "own_identity",
            "Individual values can tighten the user's own effective behavior.",
            ["scope_type must be individual", "scope_id must match the subject email"],
            ["values_docs._can_write", "values.apply_value_overlays"],
        )
    if action in {"values.write.role", "values.write.team", "values.write.department"}:
        if caps.get("can_edit_governance") and admin_scope in {"tenant", "platform"}:
            scope = "all_tenants" if admin_scope == "platform" else "own_tenant"
            return out(
                "conditional",
                scope,
                "Governance editors can write scoped values without widening role capabilities.",
                ["scope tenant must be within the admin boundary", "values overlays can only tighten effective caps"],
                ["admin.can_edit_governance", "values.apply_value_overlays"],
            )
        return out(
            "deny",
            "none",
            "Role does not have governance edit capability.",
            ["requires can_edit_governance and tenant or platform admin scope"],
            ["admin.can_edit_governance"],
        )
    if action == "values.write.organization":
        if caps.get("can_edit_governance") and admin_scope == "platform":
            return out(
                "conditional",
                "organization",
                "Only platform governance editors can change organization-wide values.",
                ["organization values affect every tenant boundary and require platform admin scope"],
                ["values_docs._can_write", "admin.scope"],
            )
        return out(
            "deny",
            "none",
            "Organization-wide values require platform admin scope.",
            ["requires can_edit_governance and admin_scope=platform"],
            ["values_docs._can_write"],
        )
    if action == "model.call":
        return out(
            "conditional",
            "request",
            "Model calls must match approved provider, model, region, purpose, and budget limits.",
            [
                f"regions={_listish(caps.get('allowed_model_regions'))}",
                f"providers={_listish(caps.get('allowed_providers'))}",
                f"max_output_tokens={caps.get('max_output_tokens')}",
                f"token_budget_per_day={caps.get('token_budget_per_day')}",
            ],
            ["model_registry", "values.resolve_values", "finops"],
        )
    if action == "model.route":
        return out(
            "conditional",
            "request",
            "Routing is constrained by residency, provider/model allowlists, and fallback policy.",
            [
                f"require_local_above_classification={caps.get('require_local_above_classification')}",
                f"fallback_mode={caps.get('fallback_mode')}",
                f"residency_strict={caps.get('residency_strict')}",
            ],
            ["routing.policy", "rbac.role_capabilities"],
        )
    if action == "tool.call":
        return out(
            "conditional",
            "request",
            "Tool invocations are allowed only after tool, egress, PII, and per-request limits pass.",
            [
                "tool_id must be present and allowed for the role",
                f"max_tool_calls_per_request={caps.get('max_tool_calls_per_request')}",
                "downstream side effects are evaluated by their own PDP actions",
            ],
            ["policy.tool.call", "tools.catalog", "egress.policy"],
        )
    if action == "egress.http":
        if "*" in egress:
            return out(
                "conditional",
                "allowlist",
                "HTTP egress is permitted to approved destinations after PII and purpose checks.",
                ["wildcard egress is platform-admin only in the default templates"],
                ["rbac.egress_domains", "egress.policy"],
            )
        if egress:
            return out(
                "conditional",
                "allowlist",
                "HTTP egress is limited to explicit approved domains.",
                [f"allowed domains={egress}", "PII and data-classification checks still apply"],
                ["rbac.egress_domains", "egress.policy"],
            )
        return out(
            "deny",
            "none",
            "Role has no approved egress destinations.",
            ["egress_domains is empty"],
            ["rbac.egress_domains"],
        )
    if action == "audit.read.own":
        if audit_scope in {"own", "team", "tenant", "all"}:
            return out("allow", "own", "Role can inspect its own audit evidence.", [], ["audit_scope"])
        return out("deny", "none", "Role has no audit read scope.", ["requires audit_scope"], ["audit_scope"])
    if action == "audit.read.tenant":
        if audit_scope in {"tenant", "all"} or admin_scope in {"tenant", "platform"}:
            scope = "all_tenants" if audit_scope == "all" or admin_scope == "platform" else "own_tenant"
            return out("conditional", scope, "Tenant audit reads are scoped to the admin boundary.", ["tenant filter is enforced"], ["audit_scope", "admin.scope"])
        return out("deny", "none", "Role cannot read tenant audit evidence.", ["requires tenant/all audit scope"], ["audit_scope"])
    if action == "audit.read.platform":
        if audit_scope == "all" or admin_scope == "platform":
            return out("allow", "all_tenants", "Platform audit reads require platform scope.", [], ["audit_scope", "admin.scope"])
        return out("deny", "none", "Platform audit reads require platform-admin scope.", ["requires audit_scope=all"], ["audit_scope"])
    if action == "finops.read":
        if admin_scope in {"tenant", "platform"}:
            scope = "all_tenants" if admin_scope == "platform" else "own_tenant"
            return out("conditional", scope, "FinOps telemetry follows the admin boundary.", ["tenant admins are tenant-filtered"], ["dashboard_api.finops", "admin.scope"])
        return out("deny", "none", "FinOps telemetry requires admin scope.", ["requires tenant or platform admin scope"], ["admin.scope"])
    if action == "policy.read":
        if admin_scope in {"tenant", "platform"}:
            scope = "all_tenants" if admin_scope == "platform" else "own_tenant"
            return out("allow", scope, "Governance state is readable inside the admin boundary.", [], ["admin.scope"])
        return out("deny", "none", "Policy inspection requires admin scope.", ["requires tenant or platform admin scope"], ["admin.scope"])
    if action == "policy.write":
        if caps.get("can_edit_governance") and admin_scope in {"tenant", "platform"}:
            scope = "all_tenants" if admin_scope == "platform" else "own_tenant"
            return out("conditional", scope, "Governance writes are allowed inside the admin boundary.", ["dual-control may apply to sensitive changes"], ["can_edit_governance", "approvals"])
        return out("deny", "none", "Governance writes require can_edit_governance.", ["requires can_edit_governance"], ["can_edit_governance"])
    if action == "user.admin":
        if caps.get("can_manage_users") and admin_scope in {"tenant", "platform"}:
            scope = "all_tenants" if admin_scope == "platform" else "own_tenant"
            return out("conditional", scope, "User administration is scoped by tenant/platform admin boundary.", ["tenant admins cannot administer other tenants"], ["can_manage_users", "admin.scope"])
        return out("deny", "none", "Role cannot administer users.", ["requires can_manage_users"], ["can_manage_users"])
    if action == "tenant.admin":
        if admin_scope == "platform":
            return out("allow", "all_tenants", "Platform admins can manage tenant lifecycle.", [], ["admin.scope", "can_delete_tenant"])
        if admin_scope == "tenant":
            return out("conditional", "own_tenant", "Tenant admins can manage configuration inside their own tenant only.", ["cannot create/delete other tenants"], ["admin.scope"])
        return out("deny", "none", "Role has no tenant administration scope.", ["requires tenant/platform admin scope"], ["admin.scope"])
    if action == "approval.review":
        can_approve = _textish(caps.get("can_approve"), "none")
        if can_approve != "none":
            return out("conditional", can_approve, "Role can review pending actions in its approval scope.", ["second-approver and dual-control rules still apply"], ["approvals", "can_approve"])
        return out("deny", "none", "Role cannot approve pending actions.", ["requires can_approve"], ["can_approve"])
    if action == "runtime.invoke":
        if caps.get("runtime_exec"):
            return out("conditional", "sandbox", "Runtime execution is allowed inside sandbox limits.", [f"network={caps.get('runtime_network')}", f"max_seconds={caps.get('runtime_max_seconds')}", f"memory_mb={caps.get('runtime_memory_mb')}"], ["policy.runtime.exec", "runtime.sandbox"])
        return out("deny", "none", "Runtime execution is disabled for this role.", ["runtime_exec=false"], ["runtime_exec"])
    if action == "runtime.python":
        if caps.get("runtime_exec") and "python" in allowed_langs:
            return out("conditional", "sandbox", "Python is allowed only in the governed runtime sandbox.", [f"allowed_runtime_languages={allowed_langs}", f"network={caps.get('runtime_network')}"], ["runtime.sandbox", "allowed_runtime_languages"])
        return out("deny", "none", "Python runtime requires runtime_exec and language allowlist.", ["requires python in allowed_runtime_languages"], ["allowed_runtime_languages"])
    if action == "cross_tenant.read":
        return out(
            "deny",
            "none",
            "Cross-tenant data reads are denied by default for every role.",
            ["resource.tenant_id must equal subject.tenant_id", "platform admin does not bypass ordinary tenant data isolation"],
            ["policy._valid_tenant", "memory.sql_tenant_filter"],
        )
    return out("unknown", "none", "No matrix rule is defined for this action.", [], ["capability_matrix"])


def _template_rows_with_defaults(template_rows: list[dict]) -> list[dict]:
    seen = {r.get("template_id") for r in template_rows}
    out = list(template_rows)
    for tid, spec in rbac.DEFAULT_TEMPLATES.items():
        if tid not in seen:
            out.append({
                "template_id": tid,
                "display_name": spec.get("display_name", tid),
                "capabilities": rbac.normalize_caps(spec.get("capabilities")),
            })
    return out


def _build_capability_matrix(principal: AdminPrincipal, template_rows: list[dict],
                             role_rows: list[dict], assignment_rows: list[dict]) -> dict:
    templates = _template_rows_with_defaults([_row_dict(r) for r in template_rows])
    template_map: dict[str, dict] = {}
    for row in templates:
        tid = row.get("template_id")
        if not tid:
            continue
        template_map[tid] = {
            "template_id": tid,
            "display_name": row.get("display_name") or tid.replace("-", " ").title(),
            "capabilities": _caps_from(row.get("capabilities")),
        }

    roles: dict[str, dict] = {}
    for tid, row in template_map.items():
        roles[tid] = {
            "role_id": tid,
            "template_id": tid,
            "display_name": row["display_name"],
            "capabilities": row["capabilities"],
            "tenant_ids": set(),
            "team_ids": set(),
            "source": "role_template",
        }

    for raw in role_rows:
        row = _row_dict(raw)
        role_id = row.get("role_id") or row.get("name")
        if not role_id:
            continue
        template_id = row.get("template_id") or role_id
        template = template_map.get(template_id) or template_map.get(role_id) or {}
        caps = _caps_from(row.get("capabilities") or template.get("capabilities"))
        item = roles.setdefault(role_id, {
            "role_id": role_id,
            "template_id": template_id,
            "display_name": template.get("display_name") or role_id.replace("-", " ").title(),
            "capabilities": caps,
            "tenant_ids": set(),
            "team_ids": set(),
            "source": "db_role",
        })
        item["capabilities"] = caps
        item["template_id"] = template_id
        item["source"] = "db_role"
        if row.get("tenant_id"):
            item["tenant_ids"].add(row["tenant_id"])
        if row.get("team_id"):
            item["team_ids"].add(row["team_id"])

    by_role_personas: dict[str, list[dict]] = {r: [] for r in roles}
    for persona in _CAPABILITY_MATRIX_PERSONAS:
        if persona["role_id"] in by_role_personas:
            by_role_personas[persona["role_id"]].append(persona)
    for raw in assignment_rows:
        row = _row_dict(raw)
        role_id = row.get("role_id")
        if not role_id or role_id not in roles:
            continue
        persona = {
            "email": row.get("user_email") or row.get("email"),
            "tenant_id": row.get("tenant_id"),
            "team_id": row.get("team_id"),
            "role_id": role_id,
            "label": row.get("user_email") or row.get("email") or role_id,
        }
        if persona["email"] and persona not in by_role_personas.setdefault(role_id, []):
            by_role_personas[role_id].append(persona)

    role_cards = []
    matrix = []
    for role_id in sorted(roles, key=lambda r: (r not in ["analyst", "lead", "tenant-admin", "platform-admin"], r)):
        item = roles[role_id]
        caps = item["capabilities"]
        tenant_ids = sorted(item["tenant_ids"])
        team_ids = sorted(item["team_ids"])
        admin_scope = _textish(caps.get("admin_scope"), "none")
        role_cards.append({
            "role_id": role_id,
            "template_id": item.get("template_id"),
            "display_name": item.get("display_name"),
            "description": item.get("display_name"),
            "source": item.get("source"),
            "tenant_ids": tenant_ids,
            "team_ids": team_ids,
            "tenant_scope": "all_tenants" if admin_scope == "platform" else ("own_tenant" if tenant_ids or admin_scope == "tenant" else "template"),
            "admin_scope": admin_scope,
            "audit_scope": _textish(caps.get("audit_scope"), "none"),
            "classification_scope": {
                "max_read_classification": caps.get("max_read_classification"),
                "max_write_classification": caps.get("max_write_classification"),
                "readable_classifications": rbac.classes_up_to(caps.get("max_read_classification")),
                "writable_classifications": rbac.classes_up_to(caps.get("max_write_classification")),
            },
            "pii_scope": _textish(caps.get("pii_scope"), "masked"),
            "memory_scope": {
                "readable_namespaces": _listish(caps.get("readable_namespaces")),
                "writable_namespaces": _listish(caps.get("writable_namespaces")),
            },
            "model_access": {
                "regions": _listish(caps.get("allowed_model_regions")),
                "providers": _listish(caps.get("allowed_providers")),
                "model_ids": _listish(caps.get("allowed_model_ids")),
                "purposes": _listish(caps.get("allowed_model_purposes")),
                "max_output_tokens": caps.get("max_output_tokens"),
                "fallback_mode": caps.get("fallback_mode"),
            },
            "budget_profile": {
                "rate_limit_per_minute": caps.get("rate_limit_per_minute"),
                "daily_request_quota": caps.get("daily_request_quota"),
                "token_budget_per_day": caps.get("token_budget_per_day"),
                "max_concurrent_requests": caps.get("max_concurrent_requests"),
            },
            "runtime_scope": {
                "runtime_exec": bool(caps.get("runtime_exec")),
                "allowed_runtime_languages": _listish(caps.get("allowed_runtime_languages")),
                "network": caps.get("runtime_network"),
                "max_seconds": caps.get("runtime_max_seconds"),
                "memory_mb": caps.get("runtime_memory_mb"),
            },
            "egress_profile": {
                "domains": _listish(caps.get("egress_domains")),
                "mode": "wildcard" if "*" in _listish(caps.get("egress_domains")) else ("allowlist" if caps.get("egress_domains") else "none"),
            },
            "cross_tenant_access": "denied_by_default",
            "persona_examples": by_role_personas.get(role_id, []),
        })
        matrix.append({
            "role_id": role_id,
            "display_name": item.get("display_name"),
            "cells": [_decision(role_id, caps, a["action"]) for a in _CAPABILITY_MATRIX_ACTIONS],
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {"admin_scope": principal.scope, "tenant_id": principal.tenant_id},
        "roles": role_cards,
        "actions": _CAPABILITY_MATRIX_ACTIONS,
        "matrix": matrix,
        "persona_examples": _CAPABILITY_MATRIX_PERSONAS,
        "scenario_map": _CAPABILITY_MATRIX_SCENARIOS,
        "notes": [
            "Skill invocation is intentionally open at skill.invoke, but each downstream memory/tool/model/runtime action is still evaluated by the PDP.",
            "Cross-tenant data reads default to deny for every role; admin scope controls governance visibility, not ordinary tenant-data bypass.",
            "Values overlays can tighten effective capabilities and do not grant more access than the underlying role template.",
        ],
    }


def _capability_matrix(principal: AdminPrincipal) -> dict:
    tenant_filter = principal.tenant_id if principal.scope == "tenant" else None
    with get_conn() as conn:
        template_rows = [dict(r) for r in conn.execute(
            "SELECT template_id, display_name, capabilities FROM role_templates ORDER BY template_id"
        ).fetchall()]
        if tenant_filter:
            role_rows = [dict(r) for r in conn.execute(
                "SELECT tenant_id, role_id, team_id, template_id, capabilities "
                "FROM roles WHERE tenant_id=%s ORDER BY tenant_id, role_id",
                (tenant_filter,),
            ).fetchall()]
            assignment_rows = [dict(r) for r in conn.execute(
                "SELECT user_email, tenant_id, team_id, role_id "
                "FROM user_assignments WHERE tenant_id=%s ORDER BY tenant_id, user_email",
                (tenant_filter,),
            ).fetchall()]
        else:
            role_rows = [dict(r) for r in conn.execute(
                "SELECT tenant_id, role_id, team_id, template_id, capabilities "
                "FROM roles ORDER BY tenant_id, role_id"
            ).fetchall()]
            assignment_rows = [dict(r) for r in conn.execute(
                "SELECT user_email, tenant_id, team_id, role_id "
                "FROM user_assignments ORDER BY tenant_id, user_email"
            ).fetchall()]
    return _build_capability_matrix(principal, template_rows, role_rows, assignment_rows)


def _seed_demo_values(tenant_id: str, actor: str) -> dict:
    """Generate illustrative org + per-team values for a tenant to exercise the cascade. Does NOT
    touch roles/capabilities, so it is safe to run on a live tenant without resetting role caps."""
    with get_conn() as conn:
        trow = conn.execute("SELECT region FROM tenants WHERE tenant_id=%s", (tenant_id,)).fetchone()
        if not trow:
            raise ValueError("tenant_not_found")
        region = trow["region"] or "AC1"
        org = {"version": "org-demo-v1", "allowed_model_region": region,
               "org_invariants": {"customer_data_boundary": "tenant", "outbound_region": region},
               **_DEMO_ORG_VALUES}
        conn.execute(
            "INSERT INTO values_rules(tenant_id, scope_type, scope_id, version, rules) "
            "VALUES (%s,'org','org',%s,%s) "
            "ON CONFLICT (tenant_id, scope_type, scope_id, version) DO UPDATE SET rules=EXCLUDED.rules",
            (tenant_id, org["version"], json.dumps(org)),
        )
        teams = [r["team_id"] for r in conn.execute(
            "SELECT team_id FROM teams WHERE tenant_id=%s ORDER BY team_id", (tenant_id,)).fetchall()]
        for tm in teams:
            tv = {"version": "team-demo-v1", "team_id": tm, **_DEMO_TEAM_VALUES}
            conn.execute(
                "INSERT INTO values_rules(tenant_id, scope_type, scope_id, version, rules) "
                "VALUES (%s,'team',%s,%s,%s) "
                "ON CONFLICT (tenant_id, scope_type, scope_id, version) DO UPDATE SET rules=EXCLUDED.rules",
                (tenant_id, tm, tv["version"], json.dumps(tv)),
            )
    _audit_admin("admin.values.seed_demo", tenant_id, tenant_id, {"teams": teams})
    return _values_view(tenant_id)


def _value_err(e: ValueError):
    code = {"tenant_not_found": 404, "role_not_found": 404, "assignment_not_found": 404,
            "team_not_found": 404, "role_exists": 409, "assignment_exists": 409,
            "team_exists": 409, "team_in_use": 409}.get(str(e), 400)
    raise HTTPException(status_code=code, detail=str(e))


@router.post("/tenants/{tenant_id}/roles", status_code=201)
async def add_role(tenant_id: str, payload: RoleCreate, principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, tenant_id)
    require_cap(principal, "can_manage_roles")
    try:
        return await run_db(_add_role, tenant_id, payload)
    except ValueError as e:
        _value_err(e)


@router.delete("/tenants/{tenant_id}/roles/{role_id}")
async def delete_role(tenant_id: str, role_id: str, principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, tenant_id)
    require_cap(principal, "can_manage_roles")
    try:
        return await run_db(_delete_role, tenant_id, role_id)
    except ValueError as e:
        _value_err(e)


@router.post("/tenants/{tenant_id}/teams", status_code=201)
async def add_team(tenant_id: str, payload: TeamCreate, principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, tenant_id)
    require_cap(principal, "can_manage_roles")
    try:
        return await run_db(_add_team, tenant_id, payload)
    except ValueError as e:
        _value_err(e)


@router.delete("/tenants/{tenant_id}/teams/{team_id}")
async def delete_team(tenant_id: str, team_id: str, principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, tenant_id)
    require_cap(principal, "can_manage_roles")
    try:
        return await run_db(_delete_team, tenant_id, team_id)
    except ValueError as e:
        _value_err(e)


@router.put("/tenants/{tenant_id}/roles/{role_id}/capabilities")
async def update_role_caps(tenant_id: str, role_id: str, payload: CapabilitiesUpdate, principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, tenant_id)
    require_cap(principal, "can_edit_governance")
    try:
        return await run_db(_update_role_caps, tenant_id, role_id, payload.capabilities)
    except ValueError as e:
        _value_err(e)


@router.put("/templates/{template_id}")
async def upsert_template(template_id: str, payload: TemplateUpsert, principal: AdminPrincipal = Depends(admin_principal)):
    require_platform(principal)
    require_cap(principal, "can_edit_governance")
    return await run_db(_upsert_template, template_id, payload)


@router.get("/users")
async def list_users(principal: AdminPrincipal = Depends(admin_principal)):
    require_cap(principal, "can_manage_users")
    users = await run_db(_list_assignments)
    if principal.scope == "tenant":
        users = [u for u in users if u["tenant_id"] == principal.tenant_id]
    return {"users": users}


@router.post("/users", status_code=201)
async def create_user(payload: AssignmentCreate, principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, payload.tenant_id)
    require_cap(principal, "can_manage_users")
    try:
        return await run_db(_create_assignment, payload)
    except ValueError as e:
        _value_err(e)


@router.put("/users/{assignment_id}")
async def update_user(assignment_id: int, payload: AssignmentUpdate, principal: AdminPrincipal = Depends(admin_principal)):
    require_cap(principal, "can_manage_users")
    tenant_filter = principal.tenant_id if principal.scope == "tenant" else None
    if payload.tenant_id and principal.scope != "platform" and payload.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="moving a user to another tenant requires platform scope")
    try:
        return await run_db(_update_assignment, assignment_id, payload, tenant_filter)
    except ValueError as e:
        if str(e) == "cross_tenant_move_forbidden":
            raise HTTPException(status_code=403, detail="cannot move a user out of your tenant")
        _value_err(e)


@router.post("/users/reset-password")
async def reset_user_password(payload: PasswordReset, principal: AdminPrincipal = Depends(admin_principal)):
    require_cap(principal, "can_manage_users")
    tenant_filter = principal.tenant_id if principal.scope == "tenant" else None
    try:
        return await run_db(_reset_user_password, payload, tenant_filter)
    except ValueError as e:
        if str(e) == "login_not_found":
            raise HTTPException(status_code=404, detail="no Keycloak login exists for this email")
        _value_err(e)


@router.post("/users/provision-login")
async def provision_user_login(payload: ProvisionLogin, principal: AdminPrincipal = Depends(admin_principal)):
    require_cap(principal, "can_manage_users")
    tenant_filter = principal.tenant_id if principal.scope == "tenant" else None
    try:
        return await run_db(_provision_login, payload, tenant_filter)
    except ValueError as e:
        _value_err(e)


@router.delete("/users/{assignment_id}")
async def delete_user(assignment_id: int, principal: AdminPrincipal = Depends(admin_principal)):
    require_cap(principal, "can_manage_users")
    tenant_filter = principal.tenant_id if principal.scope == "tenant" else None
    try:
        return await run_db(_delete_assignment, assignment_id, tenant_filter)
    except ValueError as e:
        _value_err(e)


@router.get("/export", response_class=PlainTextResponse)
async def export_state_seed(principal: AdminPrincipal = Depends(admin_principal)):
    """Return the current governance state as an idempotent SQL seed (platform scope).
    The same content is written continuously to AEGIS_EXPORT_PATH by the background exporter;
    this endpoint is the on-demand/manual trigger (e.g. `curl ... > exports/seed-state.sql`)."""
    require_platform(principal)
    require_cap(principal, "can_edit_governance")
    return await run_db(export_state.build_seed_sql)


@router.get("/model")
async def get_default_model(principal: AdminPrincipal = Depends(admin_principal)):
    require_platform(principal)
    require_cap(principal, "can_edit_governance")
    return await run_db(_model_view)


@router.put("/model")
async def set_default_model(payload: DefaultModel, principal: AdminPrincipal = Depends(admin_principal)):
    require_platform(principal)
    require_cap(principal, "can_edit_governance")
    try:
        return await run_db(_set_default_model, payload, principal.email)
    except ValueError as e:
        if str(e) == "unknown_model":
            raise HTTPException(status_code=400, detail="unknown model id (not in the registry)")
        _value_err(e)


@router.get("/tenants/{tenant_id}/values")
async def get_tenant_values(tenant_id: str, principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, tenant_id)
    return await run_db(_values_view, tenant_id)


@router.get("/tenants/{tenant_id}/values/effective")
async def get_effective_values(tenant_id: str, team: str, role: str, user: str = "preview@user",
                               principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, tenant_id)
    return await run_db(_effective_values, tenant_id, team, role, user)


@router.get("/governance/capability-matrix")
async def governance_capability_matrix(principal: AdminPrincipal = Depends(admin_principal)):
    return await run_db(_capability_matrix, principal)


@router.post("/tenants/{tenant_id}/values/seed-demo")
async def seed_demo_values(tenant_id: str, principal: AdminPrincipal = Depends(admin_principal)):
    scope_tenant(principal, tenant_id)
    require_cap(principal, "can_edit_governance")
    try:
        return await run_db(_seed_demo_values, tenant_id, principal.email)
    except ValueError as e:
        _value_err(e)



# ---------------------------------------------------------------------------
# v1.21 PAI slice 3: turn feedback endpoints.
# POST /admin/turn-feedback        any signed-in user records a thumbs +/- on a turn
# GET  /admin/turn-feedback/low    admin scopes (audit) read the low-rated queue
# GET  /admin/turn-feedback/skills admin scopes read per-skill rolling counts
# ---------------------------------------------------------------------------

from . import feedback as feedback_mod  # noqa: E402


class _FeedbackBody(BaseModel):
    trace_id: str
    rating: int                 # -1 or +1
    note: str | None = None
    skill_id: str | None = None


@router.post("/turn-feedback", status_code=201)
async def post_turn_feedback(body: _FeedbackBody,
                             subject: Subject = Depends(get_subject)):
    """Any authenticated principal can rate their own turn. The thumbs widget
    in Chat calls this; admin scopes are not required."""
    if body.rating not in (-1, 1):
        raise HTTPException(status_code=400, detail="rating must be -1 or 1")
    fb = feedback_mod.Feedback(trace_id=body.trace_id, rating=body.rating,
                               note=body.note, skill_id=body.skill_id)
    fid = await run_db(feedback_mod.record, subject.tenant_id, subject.email, fb)
    _audit_admin("turn.feedback.record", body.trace_id, subject.tenant_id,
                 {"rating": body.rating, "skill_id": body.skill_id})
    return {"id": fid}


@router.get("/turn-feedback/low")
async def get_low_rated(limit: int = 50,
                        principal: AdminPrincipal = Depends(admin_principal)):
    """Recent thumbs-down turns for the principal's tenant scope. Used by the
    Audit tab's low-rated panel."""
    if principal.audit_scope == "none":
        raise HTTPException(status_code=403, detail="audit scope required")
    tenant = principal.tenant_id or "*"
    rows = await run_db(feedback_mod.list_low_rated, tenant, limit)
    return {"items": rows, "count": len(rows)}


@router.get("/turn-feedback/skills")
async def get_skill_summary(principal: AdminPrincipal = Depends(admin_principal)):
    """Per-skill thumbs aggregates for the per-skill VERIFY trend line."""
    if principal.audit_scope == "none":
        raise HTTPException(status_code=403, detail="audit scope required")
    tenant = principal.tenant_id or "*"
    rows = await run_db(feedback_mod.skill_summary, tenant)
    return {"items": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# v1.22 MCP gateway endpoints. Servers go through the dual-control queue:
#   POST /admin/mcp/register     -- queue a registration (sign + scan up front)
#   GET  /admin/mcp/servers      -- list registered servers (any status)
#   POST /admin/mcp/<id>/quarantine  -- pull a server offline (platform-admin only)
# ---------------------------------------------------------------------------

from . import approvals as _approvals  # noqa: E402
from . import mcp_gateway as _mcp      # noqa: E402


class _MCPToolSpec(BaseModel):
    tool_id: str
    description: str = ""
    parameters: dict = Field(default_factory=dict)
    pii_class: str = "med"
    egress: str | None = None


class _MCPRegisterRequest(BaseModel):
    server_id: str
    display_name: str
    version: str
    public_key: str           # base64 ed25519
    signature: str            # base64 over canonical tools
    tools: list[_MCPToolSpec]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    notes: str = ""


@router.post("/mcp/register", status_code=202)
async def mcp_register(body: _MCPRegisterRequest,
                       principal: AdminPrincipal = Depends(admin_principal)):
    if principal.scope != "platform":
        raise HTTPException(status_code=403, detail="platform-admin scope required")
    manifest = _mcp.ServerManifest(
        server_id=body.server_id, display_name=body.display_name, version=body.version,
        public_key=body.public_key, signature=body.signature,
        tools=[_mcp.ToolSpec(tool_id=t.tool_id, description=t.description,
                             parameters=t.parameters, pii_class=t.pii_class,
                             egress=t.egress) for t in body.tools],
        command=body.command, args=body.args, env=body.env, cwd=body.cwd, notes=body.notes,
    )
    verdict = _mcp.verify_manifest(manifest)
    if not verdict["signature_ok"]:
        raise HTTPException(status_code=400, detail="signature_invalid")
    if not verdict["scan_ok"]:
        raise HTTPException(status_code=400, detail={"error": "scan_denied",
                                                      "per_tool": verdict["per_tool"]})

    # Persist in pending state + tools rows so the catalog can show them
    # alongside the approval flow.
    def _do():
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO mcp_servers(server_id, display_name, version, manifest_hash, "
                "                        public_key, command, args, env, cwd, notes, registered_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (server_id) DO UPDATE SET version=EXCLUDED.version, "
                "  manifest_hash=EXCLUDED.manifest_hash, public_key=EXCLUDED.public_key, "
                "  status='pending_approval', approved_by=NULL, approved_at=NULL",
                (manifest.server_id, manifest.display_name, manifest.version, verdict["manifest_hash"],
                 manifest.public_key, manifest.command, json.dumps(manifest.args),
                 json.dumps(manifest.env), manifest.cwd, manifest.notes, principal.email),
            )
            # Replace tools on re-registration.
            conn.execute("DELETE FROM mcp_tools WHERE server_id=%s", (manifest.server_id,))
            for t in manifest.tools:
                conn.execute(
                    "INSERT INTO mcp_tools(server_id, tool_id, description, parameters, "
                    "                       pii_class, egress, scan_action) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (manifest.server_id, t.tool_id, t.description, json.dumps(t.parameters),
                     t.pii_class, t.egress, verdict["per_tool"][t.tool_id]["action"]),
                )
    await run_db(_do)

    from .settings import settings as _settings  # v1.23.4 -- read mcp_require_dual_control
    if _settings.mcp_require_dual_control:
        # Original governance frame: queue dual-control. BR-SOD-02 -- the
        # approver must be a different platform admin than the requester.
        pending = await run_db(_approvals.create_pending,
                               principal.tenant_id or "*", "mcp.register",
                               {"server_id": manifest.server_id, "version": manifest.version,
                                "manifest_hash": verdict["manifest_hash"],
                                "namespace": verdict["namespace"]},
                               principal.email,
                               "MCP server registration awaiting second-admin approval")
        _audit_admin("mcp.register.queued", manifest.server_id, principal.tenant_id or "*",
                     {"manifest_hash": verdict["manifest_hash"],
                      "tools": verdict["namespace"], "pending_id": pending["pending_id"]})
        return {"status": "pending_approval", "pending_id": pending["pending_id"],
                "manifest_hash": verdict["manifest_hash"], "namespace": verdict["namespace"]}

    # Auto-approve: after signature + scan succeed, mark the row approved
    # immediately. The verification verdict + approver=registered_by are
    # both recorded in the audit chain so an auditor can later see exactly
    # what was checked and by whom.
    def _approve_inline():
        with get_conn() as conn:
            conn.execute(
                "UPDATE mcp_servers SET status='approved', approved_by=%s, approved_at=now() "
                "WHERE server_id=%s",
                (principal.email, manifest.server_id),
            )
    await run_db(_approve_inline)
    _audit_admin("mcp.register.auto-approved", manifest.server_id, principal.tenant_id or "*",
                 {"manifest_hash": verdict["manifest_hash"],
                  "tools": verdict["namespace"],
                  "signature_ok": verdict["signature_ok"],
                  "scan_ok": verdict["scan_ok"],
                  "approver": principal.email,
                  "policy": "AEGIS_MCP_REQUIRE_DUAL_CONTROL=false"})
    return {"status": "approved",
            "manifest_hash": verdict["manifest_hash"],
            "namespace": verdict["namespace"],
            "approver": principal.email,
            "policy": "auto_approved_after_scan_and_verify"}


@router.get("/mcp/servers")
async def mcp_list_servers(principal: AdminPrincipal = Depends(admin_principal)):
    if principal.audit_scope == "none":
        raise HTTPException(status_code=403, detail="audit scope required")
    def _do():
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT s.server_id, s.display_name, s.version, s.status, s.manifest_hash, "
                "       s.command, s.args, s.cwd, s.registered_by, s.approved_by, "
                "       s.created_at::text AS created_at, s.approved_at::text AS approved_at, "
                "       COALESCE("
                "         (SELECT json_agg(json_build_object('tool_id', t.tool_id, "
                "                                            'description', t.description, "
                "                                            'scan_action', t.scan_action)) "
                "          FROM mcp_tools t WHERE t.server_id = s.server_id), '[]'::json) AS tools "
                "FROM mcp_servers s ORDER BY s.created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    items = await run_db(_do)
    return {"items": items, "count": len(items)}


@router.post("/mcp/{server_id}/quarantine", status_code=200)
async def mcp_quarantine(server_id: str,
                         principal: AdminPrincipal = Depends(admin_principal)):
    if principal.scope != "platform":
        raise HTTPException(status_code=403, detail="platform-admin scope required")
    def _do():
        with get_conn() as conn:
            conn.execute("UPDATE mcp_servers SET status='quarantined' WHERE server_id=%s",
                         (server_id,))
    await run_db(_do)
    _audit_admin("mcp.quarantine", server_id, principal.tenant_id or "*",
                 {"by": principal.email})
    return {"server_id": server_id, "status": "quarantined"}


# ---------------------------------------------------------------------------
# v1.23 -- demo shortcut. Generates an ephemeral keypair, signs the bundled
# services/demo_mcp manifest, and routes through the standard register path.
# Same governance flow (signature verified, scan applied, dual-control queued).
# ---------------------------------------------------------------------------

@router.post("/mcp/register-demo", status_code=202)
async def mcp_register_demo(principal: AdminPrincipal = Depends(admin_principal)):
    if principal.scope != "platform":
        raise HTTPException(status_code=403, detail="platform-admin scope required")
    import base64 as _b64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey as _Ed
    priv = _Ed.generate()
    tools = [
        _mcp.ToolSpec(tool_id="pubmed_search",
                      description="Search PubMed for biomedical papers matching a query.",
                      parameters={"type": "object",
                                  "properties": {"query": {"type": "string"},
                                                  "max_results": {"type": "integer", "default": 5}},
                                  "required": ["query"]}),
        _mcp.ToolSpec(tool_id="kb_query",
                      description="Look up an internal KB note by free-text query.",
                      parameters={"type": "object",
                                  "properties": {"query": {"type": "string"}},
                                  "required": ["query"]}),
    ]
    pub_b64 = _b64.b64encode(priv.public_key().public_bytes_raw()).decode()
    sig_b64 = _b64.b64encode(priv.sign(_mcp._canonical_tools_bytes(tools))).decode()
    body = _MCPRegisterRequest(
        server_id="demo-mcp", display_name="Aegis Demo MCP", version="1.0.0",
        public_key=pub_b64, signature=sig_b64,
        tools=[_MCPToolSpec(tool_id=t.tool_id, description=t.description,
                             parameters=t.parameters, pii_class=t.pii_class,
                             egress=t.egress) for t in tools],
        command="python3", args=["-m", "services.demo_mcp.server"], cwd="/app",
        notes="bundled reference server (v1.23) -- pubmed_search + kb_query stubs",
    )
    return await mcp_register(body, principal)

# ---------------------------------------------------------------------------
# v1.23.2 -- Discover from PyPI helper.
# Runs pip install + spawn + initialize + tools/list + sign in the api
# container, returns the three values the register form needs (public_key,
# signature, tools) plus suggested launch fields. The user reviews and
# submits via the normal /admin/mcp/register path so the same governance
# (signature verify, scan, dual-control) still applies.
# ---------------------------------------------------------------------------

class _MCPDiscoverRequest(BaseModel):
    pypi_package: str
    module_path: str
    pip_timeout_s: int = 180
    handshake_timeout_s: int = 15


@router.post("/mcp/discover")
async def mcp_discover(body: _MCPDiscoverRequest,
                       principal: AdminPrincipal = Depends(admin_principal)):
    if principal.scope != "platform":
        raise HTTPException(status_code=403, detail="platform-admin scope required")

    import re as _re
    if not _re.match(r"^[A-Za-z0-9._\-]+$", body.pypi_package):
        raise HTTPException(status_code=400, detail="invalid pypi_package (chars: A-Z a-z 0-9 . _ -)")
    if not _re.match(r"^[A-Za-z0-9._]+$", body.module_path):
        raise HTTPException(status_code=400, detail="invalid module_path (chars: A-Z a-z 0-9 . _)")

    def _do():
        import base64 as _b64
        import json as _json
        import select as _sel
        import subprocess as _sub
        import time as _t
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey as _Ed

        # 1) pip install (idempotent; already-installed = no-op).
        r = _sub.run(["pip", "install", "--no-cache-dir", body.pypi_package],
                     capture_output=True, text=True, timeout=body.pip_timeout_s)
        if r.returncode != 0:
            tail = (r.stderr or r.stdout)[-600:]
            raise RuntimeError(f"pip install failed: {tail.strip()}")

        # 2) spawn the server + run the MCP handshake + tools/list.
        proc = _sub.Popen(
            ["python", "-m", body.module_path],
            stdin=_sub.PIPE, stdout=_sub.PIPE, stderr=_sub.PIPE, text=True, bufsize=1,
        )
        try:
            proc.stdin.write(_json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "aegis-discover", "version": "0"}}}) + "\n")
            proc.stdin.write(_json.dumps({"jsonrpc": "2.0", "id": 2,
                                          "method": "tools/list", "params": {}}) + "\n")
            proc.stdin.flush()

            tools_raw = None
            deadline = _t.monotonic() + body.handshake_timeout_s
            while _t.monotonic() < deadline and tools_raw is None:
                rd, _w, _x = _sel.select([proc.stdout], [], [], 0.5)
                if not rd:
                    if proc.poll() is not None:
                        err = proc.stderr.read() if proc.stderr else ""
                        raise RuntimeError(f"server exited (code={proc.returncode}) before tools/list. stderr: {err[-300:]}")
                    continue
                line = proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if msg.get("id") == 2:
                    if "error" in msg:
                        raise RuntimeError(f"tools/list error: {msg['error']}")
                    tools_raw = msg["result"]["tools"]
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001, S110
                    pass

        if tools_raw is None:
            raise RuntimeError("no tools/list response received within handshake timeout")

        # 3) reshape MCP shape -> Aegis ToolSpec field names.
        tools = [{"tool_id": t["name"],
                  "description": t.get("description", ""),
                  "parameters": t.get("inputSchema", {})} for t in tools_raw]

        # 4) sign with an ephemeral keypair so the register endpoint accepts it.
        specs = [_mcp.ToolSpec(tool_id=t["tool_id"], description=t["description"],
                                parameters=t["parameters"]) for t in tools]
        canon = _mcp._canonical_tools_bytes(specs)
        priv = _Ed.generate()
        pub_b64 = _b64.b64encode(priv.public_key().public_bytes_raw()).decode()
        sig_b64 = _b64.b64encode(priv.sign(canon)).decode()

        return {
            "public_key": pub_b64,
            "signature": sig_b64,
            "tools": tools,
            "tools_count": len(tools),
            "suggested_command": "python",
            "suggested_args": ["-m", body.module_path],
            "suggested_cwd": "/app",
            "pip_log_tail": (r.stdout or "")[-300:],
        }

    try:
        result = await run_db(_do)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"discovery failed: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=504, detail=f"discovery timed out: {e}") from e
    return result



# ---------------------------------------------------------------------------
# v1.23.5 -- DELETE /admin/mcp/{server_id}
# Remove a server in any status (pending_approval / approved / quarantined).
# Cascades to mcp_tools via the FK, and also cleans up any orphan
# pending_actions row for this registration so the Approvals tab is tidy.
# ---------------------------------------------------------------------------

@router.delete("/mcp/{server_id}", status_code=200)
async def mcp_remove(server_id: str,
                     principal: AdminPrincipal = Depends(admin_principal)):
    if principal.scope != "platform":
        raise HTTPException(status_code=403, detail="platform-admin scope required")

    def _do():
        with get_conn() as conn:
            # Capture pre-deletion state for the audit event.
            row = conn.execute(
                "SELECT status, manifest_hash FROM mcp_servers WHERE server_id=%s",
                (server_id,),
            ).fetchone()
            if not row:
                return None
            # Drop any orphan pending_actions for this server. (When the
            # dual-control flow created a row, removing the server should
            # tidy it up so the Approvals tab doesn't show a ghost.)
            conn.execute(
                "DELETE FROM pending_actions WHERE action='mcp.register' "
                "AND status='pending' AND (resource->>'server_id') = %s",
                (server_id,),
            )
            # FK on mcp_tools(server_id) is ON DELETE CASCADE.
            conn.execute("DELETE FROM mcp_servers WHERE server_id=%s", (server_id,))
            return dict(row)
    pre = await run_db(_do)
    if not pre:
        raise HTTPException(status_code=404, detail=f"server not found: {server_id}")
    _audit_admin("mcp.server.removed", server_id, principal.tenant_id or "*",
                 {"prior_status": pre["status"], "manifest_hash": pre["manifest_hash"],
                  "by": principal.email})
    return {"server_id": server_id, "status": "removed", "prior_status": pre["status"]}

# ---------------------------------------------------------------------------
# v1.23.6 -- Discover from Docker image.
# Same flow as /admin/mcp/discover but the server is spawned as a Docker
# container (docker run -i --rm <image>) instead of via Python. Covers the
# Docker MCP Hub catalogue (mcp/* images) which are not on PyPI.
# Requires the docker CLI inside the api container (added in Dockerfile.api).
# ---------------------------------------------------------------------------

class _MCPDiscoverDockerRequest(BaseModel):
    docker_image: str                      # e.g. "mcp/aws-core" or "mcp/paper-search:latest"
    extra_env: dict[str, str] = Field(default_factory=dict)
    pull_timeout_s: int = 300
    handshake_timeout_s: int = 20


@router.post("/mcp/discover-docker")
async def mcp_discover_docker(body: _MCPDiscoverDockerRequest,
                              principal: AdminPrincipal = Depends(admin_principal)):
    if principal.scope != "platform":
        raise HTTPException(status_code=403, detail="platform-admin scope required")

    import re as _re
    # Allow standard Docker image refs: name, namespace/name, name:tag, name@sha256:...
    if not _re.match(r"^[A-Za-z0-9][A-Za-z0-9._/\-:@]*$", body.docker_image):
        raise HTTPException(status_code=400,
                            detail="invalid docker_image (alphanumeric, . _ - / : @ only)")

    def _do():
        import base64 as _b64
        import json as _json
        import select as _sel
        import subprocess as _sub
        import time as _t
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey as _Ed

        # 1) pull (idempotent).
        r = _sub.run(["docker", "pull", body.docker_image],
                     capture_output=True, text=True, timeout=body.pull_timeout_s)
        if r.returncode != 0:
            tail = (r.stderr or r.stdout)[-600:]
            raise RuntimeError(f"docker pull failed: {tail.strip()}")

        # 2) run with stdio attached + handshake.
        env_args = []
        for k, v in body.extra_env.items():
            env_args.extend(["-e", f"{k}={v}"])
        run_args = ["docker", "run", "-i", "--rm", *env_args, body.docker_image]
        proc = _sub.Popen(run_args, stdin=_sub.PIPE, stdout=_sub.PIPE, stderr=_sub.PIPE,
                          text=True, bufsize=1)
        try:
            proc.stdin.write(_json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "aegis-discover-docker", "version": "0"}}}) + "\n")
            proc.stdin.write(_json.dumps({"jsonrpc": "2.0", "id": 2,
                                          "method": "tools/list", "params": {}}) + "\n")
            proc.stdin.flush()

            tools_raw = None
            deadline = _t.monotonic() + body.handshake_timeout_s
            while _t.monotonic() < deadline and tools_raw is None:
                rd, _w, _x = _sel.select([proc.stdout], [], [], 0.5)
                if not rd:
                    if proc.poll() is not None:
                        err = proc.stderr.read() if proc.stderr else ""
                        raise RuntimeError(f"container exited (code={proc.returncode}) before tools/list. stderr: {err[-300:]}")
                    continue
                line = proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if msg.get("id") == 2:
                    if "error" in msg:
                        raise RuntimeError(f"tools/list error: {msg['error']}")
                    tools_raw = msg["result"]["tools"]
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001, S110
                    pass

        if tools_raw is None:
            raise RuntimeError("no tools/list response received within handshake timeout")

        tools = [{"tool_id": t["name"],
                  "description": t.get("description", ""),
                  "parameters": t.get("inputSchema", {})} for t in tools_raw]
        specs = [_mcp.ToolSpec(tool_id=t["tool_id"], description=t["description"],
                                parameters=t["parameters"]) for t in tools]
        canon = _mcp._canonical_tools_bytes(specs)
        priv = _Ed.generate()
        pub_b64 = _b64.b64encode(priv.public_key().public_bytes_raw()).decode()
        sig_b64 = _b64.b64encode(priv.sign(canon)).decode()

        suggested_args = ["run", "-i", "--rm", *env_args, body.docker_image]
        return {
            "public_key": pub_b64,
            "signature": sig_b64,
            "tools": tools,
            "tools_count": len(tools),
            "suggested_command": "docker",
            "suggested_args": suggested_args,
            "suggested_cwd": "/app",
            "pull_log_tail": (r.stdout or "")[-300:],
        }

    try:
        result = await run_db(_do)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"docker discovery failed: {e}") from e
    return result
