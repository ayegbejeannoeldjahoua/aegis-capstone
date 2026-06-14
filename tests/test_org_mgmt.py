"""Teams management (add/delete) and assignment move/edit. DB faked; no live services."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aegis_fabric.admin as admin
from aegis_fabric.auth import AdminPrincipal


class _Res:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class FakeConn:
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
            return _Res(row={"team_id": "x", "role_id": "x"})
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
    monkeypatch.setattr(admin, "_audit_admin", lambda *a, **k: None)


# ---- add/delete team -------------------------------------------------------
def test_add_team_ok(monkeypatch):
    conn = FakeConn(present={"FROM tenants WHERE tenant_id": {"x": 1}, "FROM teams WHERE tenant_id": None})
    _patch(monkeypatch, conn)
    out = admin._add_team("acme-corp", admin.TeamCreate(team_id="finance", display_name="Finance"))
    assert out["team_id"] == "finance" and out["display_name"] == "Finance"
    assert any(x.startswith("INSERT INTO teams") for x in conn.executed)


def test_add_team_default_display(monkeypatch):
    conn = FakeConn(present={"FROM tenants WHERE tenant_id": {"x": 1}, "FROM teams WHERE tenant_id": None})
    _patch(monkeypatch, conn)
    out = admin._add_team("acme-corp", admin.TeamCreate(team_id="legal-ops"))
    assert out["display_name"] == "Legal Ops"  # derived from team_id


def test_add_team_tenant_missing(monkeypatch):
    conn = FakeConn(present={"FROM tenants WHERE tenant_id": None})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._add_team("ghost", admin.TeamCreate(team_id="finance"))
    assert str(e.value) == "tenant_not_found"


def test_add_team_conflict(monkeypatch):
    conn = FakeConn(present={"FROM tenants WHERE tenant_id": {"x": 1}, "FROM teams WHERE tenant_id": {"x": 1}})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._add_team("acme-corp", admin.TeamCreate(team_id="research"))
    assert str(e.value) == "team_exists"


def test_team_id_validation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        admin.TeamCreate(team_id="Bad Team!")


def test_delete_team_ok(monkeypatch):
    conn = FakeConn(present={"FROM roles WHERE tenant_id": None})  # no roles use it
    _patch(monkeypatch, conn)
    out = admin._delete_team("acme-corp", "finance")
    assert out["ok"] is True
    assert any(x.startswith("DELETE FROM teams") for x in conn.executed)


def test_delete_team_in_use(monkeypatch):
    conn = FakeConn(present={"FROM roles WHERE tenant_id": {"x": 1}})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._delete_team("acme-corp", "research")
    assert str(e.value) == "team_in_use"


def test_delete_team_not_found(monkeypatch):
    conn = FakeConn(present={"FROM roles WHERE tenant_id": None, "DELETE FROM teams": None})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._delete_team("acme-corp", "ghost")
    assert str(e.value) == "team_not_found"


# ---- move / edit assignment ------------------------------------------------
_CUR = {"assignment_id": 7, "user_email": "pat@acme-corp.example",
        "tenant_id": "acme-corp", "team_id": "research", "role_id": "lead"}


def test_update_assignment_move_ok(monkeypatch):
    conn = FakeConn(present={"FROM user_assignments WHERE assignment_id": _CUR,
                             "FROM roles WHERE tenant_id": {"x": 1}})
    _patch(monkeypatch, conn)
    out = admin._update_assignment(7, admin.AssignmentUpdate(tenant_id="it", role_id="platform-admin"), None)
    assert out["tenant_id"] == "it" and out["role_id"] == "platform-admin"
    assert out["team_id"] == "research"  # unchanged (omitted)
    assert any(x.startswith("UPDATE user_assignments SET tenant_id") for x in conn.executed)


def test_update_assignment_not_found(monkeypatch):
    conn = FakeConn(present={"FROM user_assignments WHERE assignment_id": None})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._update_assignment(99, admin.AssignmentUpdate(role_id="x"), None)
    assert str(e.value) == "assignment_not_found"


def test_update_assignment_target_role_missing(monkeypatch):
    conn = FakeConn(present={"FROM user_assignments WHERE assignment_id": _CUR,
                             "FROM roles WHERE tenant_id": None})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._update_assignment(7, admin.AssignmentUpdate(role_id="nope"), None)
    assert str(e.value) == "role_not_found"


def test_update_assignment_tenant_scoped_blocks_cross_tenant(monkeypatch):
    conn = FakeConn(present={"FROM user_assignments WHERE assignment_id": _CUR,
                             "FROM roles WHERE tenant_id": {"x": 1}})
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._update_assignment(7, admin.AssignmentUpdate(tenant_id="beta-corp"), tenant_filter="acme-corp")
    assert str(e.value) == "cross_tenant_move_forbidden"


# ---- endpoint scope --------------------------------------------------------
def _app(principal):
    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.admin_principal] = lambda: principal
    return app


def test_tenant_admin_cannot_move_cross_tenant(monkeypatch):
    monkeypatch.setattr(admin, "_update_assignment", lambda *a, **k: {"ok": True})
    ta = AdminPrincipal(scope="tenant", tenant_id="acme-corp", can_manage_users=True)
    with TestClient(_app(ta)) as c:
        r = c.put("/admin/users/7", json={"tenant_id": "beta-corp", "role_id": "analyst"})
    assert r.status_code == 403


def test_platform_admin_can_move_cross_tenant(monkeypatch):
    monkeypatch.setattr(admin, "_update_assignment",
                        lambda aid, u, tf: {"assignment_id": aid, "tenant_id": u.tenant_id, "role_id": u.role_id})
    pa = AdminPrincipal(scope="platform", tenant_id=None, can_manage_users=True)
    with TestClient(_app(pa)) as c:
        r = c.put("/admin/users/7", json={"tenant_id": "it", "role_id": "platform-admin"})
    assert r.status_code == 200, r.text
    assert r.json()["tenant_id"] == "it"


def test_add_team_endpoint_requires_admin():
    app = FastAPI()
    app.include_router(admin.router)
    with TestClient(app) as c:
        r = c.post("/admin/tenants/acme-corp/teams", json={"team_id": "finance"})
    assert r.status_code == 401
