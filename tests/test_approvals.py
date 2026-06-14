"""v1.7.0 dual-control: pending_actions lifecycle + two-person rule + endpoint scope."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aegis_fabric.admin as admin
import aegis_fabric.approvals as approvals
from aegis_fabric.auth import AdminPrincipal


class _Res:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []
        self.executed = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.executed.append(s)
        if s.startswith("INSERT INTO pending_actions"):
            return _Res(row={"id": 1, "status": "pending", "expires_at": None})
        if s.startswith("SELECT * FROM pending_actions"):
            return _Res(row=self.row)
        if s.startswith("SELECT id, tenant_id, action"):
            return _Res(rows=self.rows)
        return _Res(row=None)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, conn):
    @contextmanager
    def fake():
        yield conn
    monkeypatch.setattr(approvals, "get_conn", fake)
    monkeypatch.setattr(approvals, "_audit", lambda *a, **k: None)


def test_create_pending(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    out = approvals.create_pending("gamma-corp", "tenant.delete", {"tenant_id": "gamma-corp"}, "pat@acme-corp.example")
    assert out["pending"] is True and out["status"] == "pending"
    assert any(x.startswith("INSERT INTO pending_actions") for x in conn.executed)


def test_approve_blocks_self_approval(monkeypatch):
    row = {"id": 1, "status": "pending", "requester": "pat@acme-corp.example", "action": "tenant.delete",
           "tenant_id": "gamma-corp", "resource": {"tenant_id": "gamma-corp"}, "expires_at": None}
    _patch(monkeypatch, FakeConn(row=row))
    with pytest.raises(ValueError) as e:
        approvals.approve(1, "pat@acme-corp.example", None)   # same as requester
    assert str(e.value) == "self_approval_forbidden"


def test_approve_executes_with_second_approver(monkeypatch):
    row = {"id": 1, "status": "pending", "requester": "pat@acme-corp.example", "action": "tenant.delete",
           "tenant_id": "gamma-corp", "resource": {"tenant_id": "gamma-corp"}, "expires_at": None}
    _patch(monkeypatch, FakeConn(row=row))
    monkeypatch.setattr(approvals, "EXECUTORS", {"tenant.delete": lambda t, r: {"ok": True, "deleted": t}})
    out = approvals.approve(1, "lee@acme-corp.example", None)   # different principal
    assert out["status"] == "executed" and out["result"]["deleted"] == "gamma-corp"


def test_approve_not_found(monkeypatch):
    _patch(monkeypatch, FakeConn(row=None))
    with pytest.raises(ValueError) as e:
        approvals.approve(99, "lee@acme-corp.example", None)
    assert str(e.value) == "approval_not_found"


def test_reject(monkeypatch):
    row = {"id": 1, "status": "pending", "requester": "pat@acme-corp.example", "action": "tenant.delete",
           "tenant_id": "gamma-corp", "resource": {}, "expires_at": None}
    _patch(monkeypatch, FakeConn(row=row))
    out = approvals.reject(1, "lee@acme-corp.example", None)
    assert out["status"] == "rejected"


# ---- endpoint scope ----
def _app(principal):
    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.admin_principal] = lambda: principal
    return app


def test_delete_tenant_enqueues_under_dual_control(monkeypatch):
    monkeypatch.setattr(admin.approvals, "create_pending", lambda *a, **k: {"pending": True, "pending_id": 7})
    pa = AdminPrincipal(scope="platform", can_delete_tenant=True, dual_control_actions=["tenant.delete"], email="pat@x")
    with TestClient(_app(pa)) as c:
        r = c.request("DELETE", "/admin/tenants/gamma-corp", json={"confirm": "gamma-corp"})
    assert r.status_code == 200 and r.json()["pending"] is True


def test_delete_tenant_direct_when_no_dual_control(monkeypatch):
    monkeypatch.setattr(admin, "_delete_tenant", lambda t: {"ok": True, "deleted": t})
    pa = AdminPrincipal(scope="platform", can_delete_tenant=True, dual_control_actions=[], email="ops")
    with TestClient(_app(pa)) as c:
        r = c.request("DELETE", "/admin/tenants/gamma-corp", json={"confirm": "gamma-corp"})
    assert r.status_code == 200 and r.json()["deleted"] == "gamma-corp"


def test_approve_requires_can_approve(monkeypatch):
    pa = AdminPrincipal(scope="tenant", tenant_id="acme-corp", can_approve="none", email="ta@acme")
    with TestClient(_app(pa)) as c:
        r = c.post("/admin/approvals/1/approve")
    assert r.status_code == 403
