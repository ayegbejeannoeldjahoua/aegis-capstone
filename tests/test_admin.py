from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import aegis_fabric.admin as admin


class _Res:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, tenant_exists=False):
        self.tenant_exists = tenant_exists
        self.executed = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.executed.append(s)
        if s.startswith("SELECT 1 FROM tenants"):
            return _Res({"x": 1} if self.tenant_exists else None)
        return _Res(None)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, conn):
    @contextmanager
    def fake():
        yield conn
    monkeypatch.setattr(admin, "get_conn", fake)
    monkeypatch.setattr(admin.rbac, "sync_opa", lambda *a, **k: True)
    monkeypatch.setattr(admin, "append_event", lambda **k: "h")


def test_create_tenant_builds_full_shape(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    out = admin._create_tenant(admin.TenantCreate(tenant_id="gamma-corp", display_name="Gamma Corp"))
    assert out["tenant_id"] == "gamma-corp"
    assert {r["role_id"] for r in out["roles"]} == {"analyst", "lead", "viewer"}
    analyst = next(r for r in out["roles"] if r["role_id"] == "analyst")
    assert "summarise-with-memory" in analyst["capabilities"]["skills"]
    assert any(x.startswith("INSERT INTO tenants") for x in conn.executed)
    assert sum(x.startswith("INSERT INTO roles") for x in conn.executed) == 3
    assert any(x.startswith("INSERT INTO values_rules") for x in conn.executed)


def test_create_tenant_conflict(monkeypatch):
    conn = FakeConn(tenant_exists=True)
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError):
        admin._create_tenant(admin.TenantCreate(tenant_id="acme-corp", display_name="dup"))


def test_create_tenant_custom_role_inherits_template(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    out = admin._create_tenant(admin.TenantCreate(
        tenant_id="delta", display_name="Delta",
        roles=[admin.RoleSpec(role_id="auditor", template_id="viewer")],
    ))
    assert [r["role_id"] for r in out["roles"]] == ["auditor"]
    assert out["roles"][0]["capabilities"]["skills"] == admin.rbac.template_capabilities("viewer")["skills"]  # inherits viewer template


def test_tenant_id_validation():
    with pytest.raises(ValidationError):
        admin.TenantCreate(tenant_id="Bad Id!", display_name="x")


def _app():
    app = FastAPI()
    app.include_router(admin.router)
    return app


def test_admin_endpoint_requires_token():
    with TestClient(_app()) as c:
        r = c.post("/admin/tenants", json={"tenant_id": "gamma", "display_name": "G"})
    assert r.status_code == 401


def test_admin_endpoint_creates_with_token(monkeypatch):
    monkeypatch.setattr(admin, "_create_tenant", lambda payload: {"tenant_id": payload.tenant_id, "roles": []})
    with TestClient(_app()) as c:
        r = c.post("/admin/tenants", headers={"X-Admin-Token": "change-me-admin-token"},
                   json={"tenant_id": "gamma", "display_name": "Gamma"})
    assert r.status_code == 201, r.text
    assert r.json()["tenant_id"] == "gamma"


def test_admin_endpoint_rejects_bad_tenant_id(monkeypatch):
    with TestClient(_app()) as c:
        r = c.post("/admin/tenants", headers={"X-Admin-Token": "change-me-admin-token"},
                   json={"tenant_id": "Bad Id!", "display_name": "x"})
    assert r.status_code == 422
