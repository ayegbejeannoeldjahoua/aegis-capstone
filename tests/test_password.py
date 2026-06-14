"""Self-service password change (/v1/me/password) and admin reset
(/admin/users/reset-password). Keycloak and DB are faked; no live services."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aegis_fabric.admin as admin
import aegis_fabric.main as main
from aegis_fabric.auth import Subject, get_subject


# --------------------------------------------------------------------------
# Admin reset: helper-level
# --------------------------------------------------------------------------
class _Res:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, assignment=True):
        self.assignment = assignment
        self.executed = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.executed.append(s)
        if "FROM user_assignments WHERE" in s:
            return _Res({"x": 1} if self.assignment else None)
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
    monkeypatch.setattr(admin, "_audit_admin", lambda *a, **k: None)


def test_reset_password_helper_ok(monkeypatch):
    conn = FakeConn(assignment=True)
    _patch(monkeypatch, conn)
    monkeypatch.setattr(admin.keycloak_admin, "set_password_by_username", lambda *a, **k: {"updated": True})
    out = admin._reset_user_password(admin.PasswordReset(email="jane@acme-corp.example", new_password="newsecret1"), None)
    assert out["updated"] is True and out["email"] == "jane@acme-corp.example"


def test_reset_password_assignment_missing(monkeypatch):
    conn = FakeConn(assignment=False)
    _patch(monkeypatch, conn)
    with pytest.raises(ValueError) as e:
        admin._reset_user_password(admin.PasswordReset(email="ghost@x.y", new_password="newsecret1"), None)
    assert str(e.value) == "assignment_not_found"


def test_reset_password_login_not_found(monkeypatch):
    conn = FakeConn(assignment=True)
    _patch(monkeypatch, conn)
    def _raise(*a, **k):
        raise ValueError("login_not_found")
    monkeypatch.setattr(admin.keycloak_admin, "set_password_by_username", _raise)
    with pytest.raises(ValueError) as e:
        admin._reset_user_password(admin.PasswordReset(email="x@y.z", new_password="newsecret1"), None)
    assert str(e.value) == "login_not_found"


def test_reset_password_short_rejected_by_model():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        admin.PasswordReset(email="x@y.z", new_password="short")


# --------------------------------------------------------------------------
# Admin reset: endpoint-level (auth + scope)
# --------------------------------------------------------------------------
def _admin_app():
    app = FastAPI()
    app.include_router(admin.router)
    return app


def test_reset_endpoint_requires_admin():
    with TestClient(_admin_app()) as c:
        r = c.post("/admin/users/reset-password", json={"email": "x@y.z", "new_password": "newsecret1"})
    assert r.status_code == 401


def test_reset_endpoint_ok_with_token(monkeypatch):
    monkeypatch.setattr(admin, "_reset_user_password", lambda p, tf: {"email": p.email, "updated": True})
    with TestClient(_admin_app()) as c:
        r = c.post("/admin/users/reset-password", headers={"X-Admin-Token": "change-me-admin-token"},
                   json={"email": "jane@acme-corp.example", "new_password": "newsecret1"})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] is True


def test_reset_endpoint_login_not_found_maps_404(monkeypatch):
    def _raise(p, tf):
        raise ValueError("login_not_found")
    monkeypatch.setattr(admin, "_reset_user_password", _raise)
    with TestClient(_admin_app()) as c:
        r = c.post("/admin/users/reset-password", headers={"X-Admin-Token": "change-me-admin-token"},
                   json={"email": "x@y.z", "new_password": "newsecret1"})
    assert r.status_code == 404


# --------------------------------------------------------------------------
# Self-service change: /v1/me/password
# --------------------------------------------------------------------------
@pytest.fixture
def me_client(monkeypatch):
    subject = Subject(sub="kc-uuid-jane", email="jane@acme-corp.example", tenant_id="acme-corp",
                      team_id="research", role="analyst", token_claims={"preferred_username": "jane"})
    main.app.dependency_overrides[get_subject] = lambda: subject
    # never let the coarse rate limiter interfere with these tests
    monkeypatch.setattr(main.limiter, "allow", lambda *a, **k: True)
    # audit is a no-op
    import aegis_fabric.audit as audit
    monkeypatch.setattr(audit, "append_event", lambda **k: "h")
    client = TestClient(main.app)
    yield client, monkeypatch
    main.app.dependency_overrides.clear()


def test_change_password_ok(me_client):
    client, mp = me_client
    mp.setattr(main, "settings", main.settings)  # keep provisioning enabled (default True)
    import aegis_fabric.keycloak_admin as ka
    mp.setattr(ka, "verify_password", lambda u, p: True)
    mp.setattr(ka, "set_password", lambda uid, np, **k: {"updated": True})
    r = client.post("/v1/me/password", json={"current_password": "oldpass1", "new_password": "newsecret1"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_change_password_wrong_current(me_client):
    client, mp = me_client
    import aegis_fabric.keycloak_admin as ka
    mp.setattr(ka, "verify_password", lambda u, p: False)
    mp.setattr(ka, "set_password", lambda *a, **k: {"updated": True})
    r = client.post("/v1/me/password", json={"current_password": "wrong", "new_password": "newsecret1"})
    assert r.status_code == 401


def test_change_password_too_short(me_client):
    client, mp = me_client
    import aegis_fabric.keycloak_admin as ka
    mp.setattr(ka, "verify_password", lambda u, p: True)
    r = client.post("/v1/me/password", json={"current_password": "oldpass1", "new_password": "short"})
    assert r.status_code == 400


def test_change_password_same_as_current(me_client):
    client, mp = me_client
    r = client.post("/v1/me/password", json={"current_password": "samesame1", "new_password": "samesame1"})
    assert r.status_code == 400


def test_change_password_provisioning_disabled(me_client):
    client, mp = me_client
    mp.setattr(main.settings, "kc_provisioning_enabled", False)
    r = client.post("/v1/me/password", json={"current_password": "oldpass1", "new_password": "newsecret1"})
    assert r.status_code == 503
