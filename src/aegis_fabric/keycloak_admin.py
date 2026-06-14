"""Minimal Keycloak admin-API client used ONLY to provision login identities
(authentication). Authorization stays in the app DB. Optional and gated by
AEGIS_KC_PROVISIONING_ENABLED; failures never corrupt the DB assignment."""
from __future__ import annotations

import httpx

from .logging_config import get_logger
from .settings import settings

logger = get_logger("aegis.kcadmin")


def _admin_token() -> str:
    url = f"{settings.kc_admin_base}/realms/master/protocol/openid-connect/token"
    with httpx.Client(timeout=10) as c:
        r = c.post(url, data={
            "grant_type": "password", "client_id": "admin-cli",
            "username": settings.kc_admin_user, "password": settings.kc_admin_password,
        })
        r.raise_for_status()
        return r.json()["access_token"]


def create_login(email: str, password: str, first_name: str = "", last_name: str = "") -> dict:
    """Create (or confirm) a Keycloak user so the person can authenticate.
    Returns {'created': bool, 'username': email}. Idempotent on 409."""
    if not settings.kc_provisioning_enabled:
        return {"created": False, "skipped": "kc_provisioning_disabled"}
    tok = _admin_token()
    base = f"{settings.kc_admin_base}/admin/realms/{settings.kc_realm}"
    body = {
        "username": email, "email": email, "enabled": True, "emailVerified": True,
        "firstName": first_name or email.split("@")[0], "lastName": last_name or "user",
        "requiredActions": [],
        "credentials": [{"type": "password", "value": password, "temporary": False}],
    }
    with httpx.Client(timeout=10) as c:
        r = c.post(f"{base}/users", headers={"Authorization": f"Bearer {tok}"}, json=body)
        if r.status_code in (200, 201):
            return {"created": True, "username": email}
        if r.status_code == 409:
            return {"created": False, "username": email, "note": "already_exists"}
        r.raise_for_status()
        return {"created": False, "username": email}


def verify_password(username: str, password: str) -> bool:
    """Re-authenticate a user's *current* password via the direct-access grant on the
    public client. Returns True iff Keycloak issues a token. Used to gate self-service
    password change so an unlocked/unattended session can't be turned into a takeover.
    Raises httpx.HTTPError if the IdP is unreachable (the caller maps this to 503)."""
    url = f"{settings.kc_admin_base}/realms/{settings.kc_realm}/protocol/openid-connect/token"
    with httpx.Client(timeout=10) as c:
        r = c.post(url, data={
            "grant_type": "password", "client_id": settings.kc_public_client_id,
            "username": username, "password": password,
        })
    if r.status_code == 200:
        return True
    if r.status_code in (400, 401):  # invalid_grant -> wrong password
        return False
    r.raise_for_status()
    return False


def set_password(user_id: str, new_password: str, temporary: bool = False) -> dict:
    """Reset a Keycloak user's password by user id (the OIDC ``sub``). Idempotent."""
    if not settings.kc_provisioning_enabled:
        return {"updated": False, "skipped": "kc_provisioning_disabled"}
    tok = _admin_token()
    base = f"{settings.kc_admin_base}/admin/realms/{settings.kc_realm}"
    with httpx.Client(timeout=10) as c:
        r = c.put(
            f"{base}/users/{user_id}/reset-password",
            headers={"Authorization": f"Bearer {tok}"},
            json={"type": "password", "value": new_password, "temporary": temporary},
        )
        if r.status_code in (200, 204):
            return {"updated": True}
        r.raise_for_status()
        return {"updated": False}


def find_user_id(username_or_email: str) -> str | None:
    """Look up a Keycloak user id by exact username, then exact email."""
    tok = _admin_token()
    base = f"{settings.kc_admin_base}/admin/realms/{settings.kc_realm}"
    with httpx.Client(timeout=10) as c:
        for param in ("username", "email"):
            r = c.get(f"{base}/users", headers={"Authorization": f"Bearer {tok}"},
                      params={param: username_or_email, "exact": "true"})
            r.raise_for_status()
            arr = r.json()
            if arr:
                return arr[0]["id"]
    return None


def set_password_by_username(username_or_email: str, new_password: str, temporary: bool = False) -> dict:
    """Admin reset: resolve the login by username/email, then set a new password.
    Raises ValueError('login_not_found') if no such Keycloak user exists."""
    if not settings.kc_provisioning_enabled:
        return {"updated": False, "skipped": "kc_provisioning_disabled"}
    uid = find_user_id(username_or_email)
    if not uid:
        raise ValueError("login_not_found")
    return set_password(uid, new_password, temporary=temporary)
