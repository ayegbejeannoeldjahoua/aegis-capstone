from __future__ import annotations

import asyncio
import hmac
import time

import httpx
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from .db import run_db
from .logging_config import get_logger
from .settings import settings

logger = get_logger("aegis.auth")
bearer = HTTPBearer(auto_error=False)


class Subject(BaseModel):
    sub: str
    email: str
    tenant_id: str
    team_id: str
    role: str
    groups: list[str] = []
    token_claims: dict


_jwks_cache: dict | None = None
_jwks_expiry = 0.0
_jwks_lock = asyncio.Lock()


def _allowed_issuers() -> tuple[str, ...]:
    """Accept both the internal (JWKS-reachable) issuer and the public issuer, so
    tokens minted via the public URL validate while keys are fetched internally."""
    issuers = [settings.oidc_issuer]
    if settings.oidc_public_issuer and settings.oidc_public_issuer not in issuers:
        issuers.append(settings.oidc_public_issuer)
    return tuple(issuers)


async def jwks(force: bool = False) -> dict:
    global _jwks_cache, _jwks_expiry
    if not force and _jwks_cache and time.time() < _jwks_expiry:
        return _jwks_cache
    async with _jwks_lock:
        if not force and _jwks_cache and time.time() < _jwks_expiry:
            return _jwks_cache
        url = f"{settings.oidc_issuer}/protocol/openid-connect/certs"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_expiry = time.time() + settings.jwks_cache_seconds
            return _jwks_cache


def _decode(token: str, keys: dict) -> dict:
    return jwt.decode(
        token, keys, algorithms=["RS256"], audience=settings.oidc_audience,
        issuer=_allowed_issuers(), options={"verify_at_hash": False},
    )


async def validate_token(token: str) -> Subject:
    # 1) Authentication: prove the token is genuine (Keycloak's job).
    try:
        keys = await jwks()
        try:
            claims = _decode(token, keys)
        except JWTError:
            keys = await jwks(force=True)  # handle signing-key rotation
            claims = _decode(token, keys)
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"invalid token: {e}")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"identity provider unreachable: {e}")

    sub = claims.get("sub", "")
    email = claims.get("email") or claims.get("preferred_username")
    email_verified = bool(claims.get("email_verified", False))
    if not sub:
        raise HTTPException(status_code=401, detail="token missing subject (sub)")

    # 2) Authorization context: the APP DB is the source of truth for tenancy/role.
    from .rbac import resolve_assignment

    assignment = await run_db(resolve_assignment, sub, email, email_verified)
    if assignment:
        tenant_id, team_id, role = assignment["tenant_id"], assignment["team_id"], assignment["role_id"]
    elif settings.allow_group_fallback:
        # Transitional fallback: derive from the token's group path /tenant/team/role.
        groups = claims.get("groups", [])
        tenant_id = _group_attr(groups, 0)
        team_id = _group_attr(groups, 1) or "research"
        role = _group_attr(groups, 2) or "viewer"
    else:
        raise HTTPException(status_code=403, detail="no tenant/role assignment for this identity")

    if not tenant_id:
        raise HTTPException(status_code=403, detail="tenant assignment missing")

    from .rbac import role_capabilities as _role_caps
    smm = (await run_db(_role_caps, tenant_id, role)).get("session_max_minutes", 0)
    if smm and smm > 0:
        iat = claims.get("iat")
        if iat and (time.time() - float(iat)) > smm * 60:
            raise HTTPException(status_code=401, detail="session expired (exceeds session_max_minutes)")

    return Subject(
        sub=sub,
        email=email or sub,
        tenant_id=tenant_id,
        team_id=team_id,
        role=role,
        groups=claims.get("groups", []),
        token_claims=claims,
    )


async def get_subject(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Subject:
    if not creds:
        raise HTTPException(status_code=401, detail="missing bearer token")
    return await validate_token(creds.credentials)


async def require_admin(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    """Guard for the administrative / governance-write surface. Constant-time shared
    secret today; replace with an OIDC platform-admin role or mTLS in production."""
    if not x_admin_token or not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=401, detail="admin authentication required")


def _group_attr(groups: list[str], idx: int):
    for g in groups:
        parts = [p for p in g.split("/") if p]
        if len(parts) >= 3:
            return parts[idx]
    return None


# ---------------------------------------------------------------------------
# Capability-based admin authorization (RBAC over the platform itself).
# An admin caller is EITHER the shared X-Admin-Token (super-admin / ops bypass)
# OR an OIDC user whose role grants an admin_scope. Tenant-admins are confined to
# their own tenant; platform-admins are unconstrained.
# ---------------------------------------------------------------------------
class AdminPrincipal(BaseModel):
    scope: str  # none | tenant | platform
    tenant_id: str | None = None
    email: str = "admin"
    can_manage_users: bool = False
    can_manage_roles: bool = False
    can_edit_governance: bool = False
    can_register_skills: bool = False
    can_delete_tenant: bool = False
    audit_scope: str = "none"
    can_approve: str = "none"            # none | team | tenant | platform
    dual_control_actions: list[str] = []
    can_rotate_secrets: bool = False
    can_view_traces: bool = False
    can_manage_signing_keys: bool = False
    can_impersonate: str = "none"        # none | read | full


async def admin_principal_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> AdminPrincipal | None:
    """Like admin_principal, but returns None instead of raising when the
    caller has no admin scope. For endpoints that need to differentiate
    admins from regular users (e.g. /values/scopes telling the UI which
    scopes to show as editable) without rejecting non-admins outright."""
    try:
        return await admin_principal(creds=creds, x_admin_token=x_admin_token)
    except HTTPException:
        return None


async def admin_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> AdminPrincipal:
    if x_admin_token and hmac.compare_digest(x_admin_token, settings.admin_token):
        return AdminPrincipal(scope="platform", tenant_id=None, email="admin-token",
                              can_manage_users=True, can_manage_roles=True, can_edit_governance=True,
                              can_register_skills=True, can_delete_tenant=True, audit_scope="all",
                              can_approve="platform", dual_control_actions=[],
                              can_rotate_secrets=True, can_view_traces=True,
                              can_manage_signing_keys=True, can_impersonate="full")
    if not creds:
        raise HTTPException(status_code=401, detail="admin authentication required")
    subject = await validate_token(creds.credentials)
    from .rbac import role_capabilities

    caps = await run_db(role_capabilities, subject.tenant_id, subject.role)
    scope = caps.get("admin_scope", "none")
    if scope == "none":
        raise HTTPException(status_code=403, detail="this role has no administrative scope")
    return AdminPrincipal(
        scope=scope, tenant_id=(None if scope == "platform" else subject.tenant_id), email=subject.email,
        can_manage_users=caps.get("can_manage_users", False), can_manage_roles=caps.get("can_manage_roles", False),
        can_edit_governance=caps.get("can_edit_governance", False),
        can_register_skills=caps.get("can_register_skills", False),
        can_delete_tenant=caps.get("can_delete_tenant", False), audit_scope=caps.get("audit_scope", "none"),
        can_approve=caps.get("can_approve", "none"), dual_control_actions=caps.get("dual_control_actions", []),
        can_rotate_secrets=caps.get("can_rotate_secrets", False), can_view_traces=caps.get("can_view_traces", False),
        can_manage_signing_keys=caps.get("can_manage_signing_keys", False),
        can_impersonate=caps.get("can_impersonate", "none"),
    )


def require_cap(principal: AdminPrincipal, cap: str) -> None:
    if not getattr(principal, cap, False):
        raise HTTPException(status_code=403, detail=f"missing capability: {cap}")


def require_platform(principal: AdminPrincipal) -> None:
    if principal.scope != "platform":
        raise HTTPException(status_code=403, detail="platform admin scope required")


def scope_tenant(principal: AdminPrincipal, tenant_id: str) -> None:
    if principal.scope == "platform":
        return
    if principal.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail=f"not authorized for tenant '{tenant_id}'")



# ---------------------------------------------------------------------------
# v1.20 BR-CAP-02 -- re-authentication freshness for sensitive actions.
#
# Even within a valid session, certain actions (dual-control approvals,
# governance writes, MCP server registrations, capability bundle changes)
# should require a recent re-authentication. This catches the case where a
# logged-in browser tab gets hijacked or left unattended for hours.
#
# Implementation: compare the JWT `iat` claim against
# sensitive_action_max_age_minutes; if too old, force the caller to re-login
# (the SPA's keycloak-js will silently refresh, or prompt for credentials).
# ---------------------------------------------------------------------------

def _token_age_seconds(claims: dict) -> float | None:
    iat = claims.get("iat")
    if iat is None:
        return None
    try:
        return max(0.0, time.time() - float(iat))
    except (TypeError, ValueError):
        return None


def require_recent_auth(subject: Subject, max_age_minutes: int | None = None) -> None:
    """Raise 401 if the token was issued more than N minutes ago.

    Defaults to settings.sensitive_action_max_age_minutes when max_age_minutes
    is None. A value of 0 disables the check (useful for tests).
    """
    n = settings.sensitive_action_max_age_minutes if max_age_minutes is None else max_age_minutes
    if n <= 0:
        return
    age = _token_age_seconds(subject.token_claims)
    if age is None:
        # No iat claim: refuse rather than fail open.
        raise HTTPException(status_code=401,
                            detail="token has no iat claim; re-login required for sensitive action")
    if age > n * 60:
        raise HTTPException(status_code=401,
                            detail=f"re-authentication required (token older than {n}m for sensitive action)")


async def recently_authenticated_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> AdminPrincipal:
    """FastAPI dependency for sensitive endpoints. Same shape as admin_principal
    but enforces the re-auth freshness window. The X-Admin-Token bypass still applies."""
    if x_admin_token and hmac.compare_digest(x_admin_token, settings.admin_token):
        return AdminPrincipal(scope="platform", tenant_id=None, email="admin-token",
                              can_manage_users=True, can_manage_roles=True, can_edit_governance=True,
                              can_register_skills=True, can_delete_tenant=True, audit_scope="all",
                              can_approve="platform", dual_control_actions=[],
                              can_rotate_secrets=True, can_view_traces=True,
                              can_manage_signing_keys=True, can_impersonate="full")
    if not creds:
        raise HTTPException(status_code=401, detail="admin authentication required")
    # Check token age
    try:
        from jose import jwt as _jwt
        _claims = _jwt.get_unverified_claims(creds.credentials)
        _iat = int(_claims.get("iat", 0))
        from datetime import datetime, timezone
        _age_min = (datetime.now(timezone.utc).timestamp() - _iat) / 60.0
        if _age_min > settings.sensitive_action_max_age_minutes:
            raise HTTPException(status_code=401, detail="re-authentication required for sensitive action")
    except HTTPException:
        raise
    except Exception:
        pass
    return await admin_principal(creds=creds, x_admin_token=x_admin_token)
