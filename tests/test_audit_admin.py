"""Admin-side audit ledger endpoints used by the Audit tab."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aegis_fabric.admin as admin
import aegis_fabric.audit as audit
from aegis_fabric.auth import AdminPrincipal


def _app(principal, monkeypatch):
    async def fake_run_db(fn, *a, **k):
        return fn(*a, **k)
    monkeypatch.setattr(admin, "run_db", fake_run_db)
    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.admin_principal] = lambda: principal
    return app


def test_admin_audit_last(monkeypatch):
    monkeypatch.setattr(audit, "last", lambda t, scope, email, limit: [{"sequence_id": 1, "action": "skill.invoke"}])
    pa = AdminPrincipal(scope="platform", audit_scope="all", email="pat@it")
    with TestClient(_app(pa, monkeypatch)) as c:
        r = c.get("/admin/audit/last?limit=50")
    assert r.status_code == 200 and r.json()["scope"] == "all" and r.json()["events"][0]["sequence_id"] == 1


def test_admin_audit_verify_gated(monkeypatch):
    monkeypatch.setattr(audit, "verify_chain", lambda *a, **k: {"ok": True, "verified": 3, "total": 3})
    ok = AdminPrincipal(scope="platform", can_view_traces=True)
    with TestClient(_app(ok, monkeypatch)) as c:
        assert c.get("/admin/audit/verify").json()["ok"] is True
    with TestClient(_app(AdminPrincipal(scope="tenant", tenant_id="acme-corp"), monkeypatch)) as c:
        assert c.get("/admin/audit/verify").status_code == 403
