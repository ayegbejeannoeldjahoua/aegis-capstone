"""Admin (re)provision-login (/admin/users/provision-login): recreate or refresh
a Keycloak login for an existing assignment, optionally clearing the stale
sub-binding so an account stranded by a Keycloak reset can sign in again.
Keycloak and DB are faked; no live services."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import aegis_fabric.admin as admin


class _Res:
    def __init__(self, rows=None):
        self._rows = rows if rows is not None else []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    """Returns the supplied assignment rows for the lookup SELECT and records
    every executed statement (so tests can assert the rebind UPDATE ran)."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [{"assignment_id": 1}]
        self.executed = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.executed.append((s, params))
        if s.startswith("SELECT assignment_id FROM user_assignments"):
            return _Res(self.rows)
        return _Res()

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


# --------------------------------------------------------------------------
# helper-level
# --------------------------------------------------------------------------
def test_provision_creates_login_and_rebinds(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    monkeypatch.setattr(admin.keycloak_admin, "create_login", lambda e, p: {"created": True, "username": e})
    out = admin._provision_login(admin.ProvisionLogin(email="legal1@acme-corp.example", password="Passw0rd!demo"), None)
    assert out["login"]["created"] is True
    assert out["rebound"] == 1
    # the stale binding must have been cleared so the fresh login re-binds
    assert any(q.startswith("UPDATE user_assignments SET sub=NULL, bound_at=NULL") for q, _ in conn.executed)


def test_provision_refreshes_existing_login_sets_password(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    monkeypatch.setattr(admin.keycloak_admin, "create_login",
                        lambda e, p: {"created": False, "username": e, "note": "already_exists"})
    monkeypatch.setattr(admin.keycloak_admin, "set_password_by_username", lambda *a, **k: {"updated": True})
    out = admin._provision_login(admin.ProvisionLogin(email="jane@acme-corp.example", password="newsecret1"), None)
    assert out["login"]["created"] is False
    assert out["login"]["password_set"] is True


def test_provision_assignment_missing(monkeypatch):
    conn = FakeConn(rows=[])
    _patch(monkeypatch, conn)
    monkeypatch.setattr(admin.keycloak_admin, "create_login", lambda e, p: {"created": True, "username": e})
    with pytest.raises(ValueError) as e:
        admin._provision_login(admin.ProvisionLogin(email="ghost@x.y", password="whatever1"), None)
    assert str(e.value) == "assignment_not_found"


def test_provision_no_rebind_skips_update(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    monkeypatch.setattr(admin.keycloak_admin, "create_login", lambda e, p: {"created": True, "username": e})
    out = admin._provision_login(admin.ProvisionLogin(email="lee@acme-corp.example", password="newsecret1", rebind=False), None)
    assert out["rebound"] == 0
    assert not any(q.startswith("UPDATE user_assignments SET sub=NULL") for q, _ in conn.executed)


def test_provision_tenant_scoped_filters_lookup_and_rebind(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    monkeypatch.setattr(admin.keycloak_admin, "create_login", lambda e, p: {"created": True, "username": e})
    admin._provision_login(admin.ProvisionLogin(email="legal1@acme-corp.example", password="Passw0rd!demo"), "acme-corp")
    # both the SELECT and the rebind UPDATE must be scoped to the admin's tenant
    select = next((q, prm) for q, prm in conn.executed if q.startswith("SELECT assignment_id"))
    update = next((q, prm) for q, prm in conn.executed if q.startswith("UPDATE user_assignments SET sub=NULL"))
    assert "tenant_id=%s" in select[0] and "acme-corp" in select[1]
    assert "tenant_id=%s" in update[0] and "acme-corp" in update[1]


def test_provision_password_too_short_rejected_by_model():
    with pytest.raises(ValidationError):
        admin.ProvisionLogin(email="x@y.z", password="short")


def test_provision_login_not_found_during_refresh_is_swallowed(monkeypatch):
    """If create_login reports not-created and set_password can't find the user
    (e.g. provisioning disabled), the helper must not blow up."""
    conn = FakeConn()
    _patch(monkeypatch, conn)
    monkeypatch.setattr(admin.keycloak_admin, "create_login",
                        lambda e, p: {"created": False, "skipped": "kc_provisioning_disabled"})

    def _raise(*a, **k):
        raise ValueError("login_not_found")
    monkeypatch.setattr(admin.keycloak_admin, "set_password_by_username", _raise)
    out = admin._provision_login(admin.ProvisionLogin(email="x@y.z", password="newsecret1"), None)
    assert out["login"]["created"] is False
    assert "password_set" not in out["login"]


# --------------------------------------------------------------------------
# endpoint-level (auth + scope + error mapping)
# --------------------------------------------------------------------------
def _admin_app():
    app = FastAPI()
    app.include_router(admin.router)
    return app


def test_provision_endpoint_requires_admin():
    with TestClient(_admin_app()) as c:
        r = c.post("/admin/users/provision-login", json={"email": "x@y.z", "password": "newsecret1"})
    assert r.status_code == 401


def test_provision_endpoint_ok_with_token(monkeypatch):
    monkeypatch.setattr(admin, "_provision_login",
                        lambda p, tf: {"email": p.email, "rebound": 1, "login": {"created": True}})
    with TestClient(_admin_app()) as c:
        r = c.post("/admin/users/provision-login", headers={"X-Admin-Token": "change-me-admin-token"},
                   json={"email": "legal1@acme-corp.example", "password": "Passw0rd!demo"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["login"]["created"] is True and body["rebound"] == 1


def test_provision_endpoint_assignment_not_found_maps_404(monkeypatch):
    def _raise(p, tf):
        raise ValueError("assignment_not_found")
    monkeypatch.setattr(admin, "_provision_login", _raise)
    with TestClient(_admin_app()) as c:
        r = c.post("/admin/users/provision-login", headers={"X-Admin-Token": "change-me-admin-token"},
                   json={"email": "ghost@x.y", "password": "newsecret1"})
    assert r.status_code == 404
