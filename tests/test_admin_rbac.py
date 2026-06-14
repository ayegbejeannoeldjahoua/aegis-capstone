import asyncio

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import aegis_fabric.admin as admin
import aegis_fabric.auth as auth
import aegis_fabric.rbac as rbac
from aegis_fabric.auth import AdminPrincipal, Subject


class _Creds:
    def __init__(self, t):
        self.credentials = t


def test_admin_principal_token_is_superadmin():
    p = asyncio.run(auth.admin_principal(creds=None, x_admin_token="change-me-admin-token"))
    assert p.scope == "platform" and p.can_manage_roles and p.can_delete_tenant and p.audit_scope == "all"


def test_admin_principal_no_creds_401():
    with pytest.raises(HTTPException) as e:
        asyncio.run(auth.admin_principal(creds=None, x_admin_token=None))
    assert e.value.status_code == 401


def test_admin_principal_oidc_tenant_admin(monkeypatch):
    async def fake_validate(token):
        return Subject(sub="s", email="ta@acme", tenant_id="acme-corp", team_id="research",
                       role="tenant-admin", token_claims={})
    monkeypatch.setattr(auth, "validate_token", fake_validate)
    monkeypatch.setattr(rbac, "role_capabilities", lambda t, r: rbac.template_capabilities("tenant-admin"))
    p = asyncio.run(auth.admin_principal(creds=_Creds("x"), x_admin_token=None))
    assert p.scope == "tenant" and p.tenant_id == "acme-corp" and p.can_manage_roles is True


def test_admin_principal_no_scope_403(monkeypatch):
    async def fake_validate(token):
        return Subject(sub="s", email="a@acme", tenant_id="acme-corp", team_id="research",
                       role="analyst", token_claims={})
    monkeypatch.setattr(auth, "validate_token", fake_validate)
    monkeypatch.setattr(rbac, "role_capabilities", lambda t, r: rbac.template_capabilities("analyst"))
    with pytest.raises(HTTPException) as e:
        asyncio.run(auth.admin_principal(creds=_Creds("x"), x_admin_token=None))
    assert e.value.status_code == 403


def _app(principal):
    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.admin_principal] = lambda: principal
    return app


def test_tenant_admin_cannot_create_tenant(monkeypatch):
    monkeypatch.setattr(admin, "_create_tenant", lambda p: {"tenant_id": p.tenant_id})
    ta = AdminPrincipal(scope="tenant", tenant_id="acme-corp", can_manage_roles=True, can_manage_users=True,
                        can_edit_governance=True)
    with TestClient(_app(ta)) as c:
        r = c.post("/admin/tenants", json={"tenant_id": "gamma", "display_name": "G"})
    assert r.status_code == 403


def test_platform_admin_can_create_tenant(monkeypatch):
    monkeypatch.setattr(admin, "_create_tenant", lambda p: {"tenant_id": p.tenant_id})
    pa = AdminPrincipal(scope="platform", tenant_id=None, can_manage_roles=True, can_manage_users=True,
                        can_edit_governance=True, can_register_skills=True)
    with TestClient(_app(pa)) as c:
        r = c.post("/admin/tenants", json={"tenant_id": "gamma", "display_name": "G"})
    assert r.status_code == 201


def test_tenant_admin_role_scope(monkeypatch):
    monkeypatch.setattr(admin, "_add_role", lambda t, p: {"tenant_id": t, "role_id": p.role_id})
    ta = AdminPrincipal(scope="tenant", tenant_id="acme-corp", can_manage_roles=True)
    with TestClient(_app(ta)) as c:
        ok = c.post("/admin/tenants/acme-corp/roles", json={"role_id": "auditor", "template_id": "viewer"})
        denied = c.post("/admin/tenants/beta-corp/roles", json={"role_id": "auditor", "template_id": "viewer"})
    assert ok.status_code == 201
    assert denied.status_code == 403


def test_role_without_capability_denied(monkeypatch):
    monkeypatch.setattr(admin, "_add_role", lambda t, p: {"tenant_id": t})
    ta = AdminPrincipal(scope="tenant", tenant_id="acme-corp", can_manage_roles=False)
    with TestClient(_app(ta)) as c:
        r = c.post("/admin/tenants/acme-corp/roles", json={"role_id": "x", "template_id": "viewer"})
    assert r.status_code == 403


def test_platform_admin_deletes_tenant_with_confirm(monkeypatch):
    monkeypatch.setattr(admin, "_delete_tenant", lambda t: {"ok": True, "deleted": t})
    pa = AdminPrincipal(scope="platform", tenant_id=None, can_delete_tenant=True)
    with TestClient(_app(pa)) as c:
        ok = c.request("DELETE", "/admin/tenants/gamma-corp", json={"confirm": "gamma-corp"})
        bad = c.request("DELETE", "/admin/tenants/gamma-corp", json={"confirm": "wrong"})
    assert ok.status_code == 200, ok.text
    assert bad.status_code == 400


def test_tenant_admin_cannot_delete_tenant(monkeypatch):
    monkeypatch.setattr(admin, "_delete_tenant", lambda t: {"ok": True})
    ta = AdminPrincipal(scope="tenant", tenant_id="acme-corp", can_manage_roles=True, can_delete_tenant=False)
    with TestClient(_app(ta)) as c:
        r = c.request("DELETE", "/admin/tenants/acme-corp", json={"confirm": "acme-corp"})
    assert r.status_code == 403  # require_platform fails


def test_platform_admin_without_delete_cap_denied(monkeypatch):
    monkeypatch.setattr(admin, "_delete_tenant", lambda t: {"ok": True})
    pa = AdminPrincipal(scope="platform", tenant_id=None, can_delete_tenant=False)
    with TestClient(_app(pa)) as c:
        r = c.request("DELETE", "/admin/tenants/gamma-corp", json={"confirm": "gamma-corp"})
    assert r.status_code == 403
