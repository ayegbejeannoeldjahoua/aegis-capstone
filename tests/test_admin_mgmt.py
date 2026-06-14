from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aegis_fabric.admin as admin


class _Res:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeConn:
    """Configurable fake: `present` decides SELECT/RETURNING existence per SQL substring."""
    def __init__(self, present=None):
        self.present = present or {}
        self.executed = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.executed.append(s)
        for needle, row in self.present.items():
            if needle in s:
                return _Res(row=row)
        if "RETURNING" in s:
            return _Res(row={"role_id": "x", "user_email": "e@x", "tenant_id": "t"})
        return _Res(row=None)

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
    monkeypatch.setattr(admin, "_audit_admin", lambda *a, **k: None)


def test_add_role_from_template(monkeypatch):
    # tenant exists, role does not
    conn = FakeConn(present={"FROM tenants WHERE tenant_id": {"x": 1}, "FROM roles WHERE tenant_id": None})
    _patch(monkeypatch, conn)
    out = admin._add_role("gamma-corp", admin.RoleCreate(role_id="auditor", template_id="viewer"))
    assert out["role_id"] == "auditor"
    assert out["capabilities"]["skills"] == admin.rbac.template_capabilities("viewer")["skills"]  # inherits viewer template
    assert any(x.startswith("INSERT INTO roles") for x in conn.executed)


def test_add_role_conflict(monkeypatch):
    conn = FakeConn(present={"FROM tenants WHERE tenant_id": {"x": 1}, "FROM roles WHERE tenant_id": {"x": 1}})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._add_role("acme-corp", admin.RoleCreate(role_id="analyst"))
    assert str(e.value) == "role_exists"


def test_update_role_caps(monkeypatch):
    conn = FakeConn(present={"UPDATE roles SET capabilities": {"role_id": "analyst"}})
    _patch(monkeypatch, conn)
    out = admin._update_role_caps("acme-corp", "analyst", {"skills": ["s1"], "junk": 1})
    assert out["capabilities"]["skills"] == ["s1"]
    assert "junk" not in out["capabilities"]  # normalized


def test_update_role_caps_missing(monkeypatch):
    conn = FakeConn(present={"UPDATE roles SET capabilities": None})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._update_role_caps("acme-corp", "ghost", {})
    assert str(e.value) == "role_not_found"


def test_create_assignment_with_login(monkeypatch):
    conn = FakeConn(present={"FROM roles WHERE tenant_id": {"x": 1}, "FROM user_assignments WHERE": None})
    _patch(monkeypatch, conn)
    monkeypatch.setattr(admin.keycloak_admin, "create_login", lambda *a, **k: {"created": True, "username": a[0]})
    out = admin._create_assignment(admin.AssignmentCreate(
        email="dana@gamma-corp.example", tenant_id="gamma-corp", role_id="analyst",
        create_login=True, password="pw"))
    assert out["login"]["created"] is True
    assert any(x.startswith("INSERT INTO user_assignments") for x in conn.executed)


def test_create_assignment_role_missing(monkeypatch):
    conn = FakeConn(present={"FROM roles WHERE tenant_id": None})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._create_assignment(admin.AssignmentCreate(email="x@y.z", tenant_id="t", role_id="nope"))
    assert str(e.value) == "role_not_found"


def test_create_assignment_login_requires_password(monkeypatch):
    conn = FakeConn(present={"FROM roles WHERE tenant_id": {"x": 1}, "FROM user_assignments WHERE": None})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._create_assignment(admin.AssignmentCreate(email="x@y.z", tenant_id="t", role_id="analyst", create_login=True))
    assert str(e.value) == "password_required_for_login"


def _app():
    app = FastAPI()
    app.include_router(admin.router)
    return app


def test_mgmt_endpoints_require_admin():
    with TestClient(_app()) as c:
        assert c.get("/admin/users").status_code == 401
        assert c.post("/admin/tenants/x/roles", json={"role_id": "r"}).status_code == 401


def test_add_role_endpoint_ok(monkeypatch):
    monkeypatch.setattr(admin, "_add_role", lambda t, p: {"tenant_id": t, "role_id": p.role_id})
    with TestClient(_app()) as c:
        r = c.post("/admin/tenants/gamma-corp/roles", headers={"X-Admin-Token": "change-me-admin-token"},
                   json={"role_id": "auditor", "template_id": "viewer"})
    assert r.status_code == 201 and r.json()["role_id"] == "auditor"


def test_delete_tenant_ok(monkeypatch):
    conn = FakeConn()  # RETURNING -> row present
    _patch(monkeypatch, conn)
    out = admin._delete_tenant("gamma-corp")
    assert out["ok"] is True and out["deleted"] == "gamma-corp"
    assert any(x.startswith("DELETE FROM tenants") for x in conn.executed)


def test_delete_tenant_not_found(monkeypatch):
    conn = FakeConn(present={"DELETE FROM tenants": None})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._delete_tenant("nope")
    assert str(e.value) == "tenant_not_found"
