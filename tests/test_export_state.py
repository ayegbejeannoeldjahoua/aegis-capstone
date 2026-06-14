"""State export (export_state.build_seed_sql + /admin/export): serialize live governance
into an idempotent SQL seed for a bare-scratch reinstall. DB is faked; no live services.
Verifies the seed is idempotent, excludes secrets/sub bindings, and the endpoint is
platform-scoped."""
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

import aegis_fabric.admin as admin
import aegis_fabric.export_state as export_state
from aegis_fabric.auth import AdminPrincipal, admin_principal


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, data):
        self.data = data

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if "MAX(sequence_id)" in s:
            return _Res([{"seq": self.data.get("seq", 0)}])
        if "FROM tenants" in s:
            return _Res(self.data.get("tenants", []))
        if "FROM role_templates" in s:
            return _Res(self.data.get("templates", []))
        if "FROM teams" in s:
            return _Res(self.data.get("teams", []))
        if "FROM roles" in s:
            return _Res(self.data.get("roles", []))
        if "FROM values_rules" in s:
            return _Res(self.data.get("values", []))
        if "FROM user_assignments" in s:
            return _Res(self.data.get("assignments", []))
        return _Res([])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_DATA = {
    "tenants": [{"tenant_id": "acme-corp", "display_name": "Acme Corp", "region": "AC1"}],
    "templates": [{"template_id": "viewer", "display_name": "Viewer", "capabilities": {"max_model_risk_tier": "T2"}}],
    "teams": [{"tenant_id": "acme-corp", "team_id": "finance", "display_name": "Finance"}],
    "roles": [{"tenant_id": "acme-corp", "role_id": "finance-lead", "team_id": "finance",
               "template_id": "lead", "capabilities": {"skills": ["assistant"], "max_read_classification": "confidential"}}],
    "values": [{"tenant_id": "acme-corp", "scope_type": "org", "scope_id": "org", "version": "v1",
                "rules": {"outbound_region": "AC1"}}],
    "assignments": [{"user_email": "pat@acme-corp.example", "tenant_id": "it",
                     "team_id": "platform", "role_id": "platform-admin"}],
    "seq": 42,
}


def _patch(monkeypatch, data=_DATA):
    @contextmanager
    def fake():
        yield FakeConn(data)
    monkeypatch.setattr(export_state, "get_conn", fake)


def test_seed_is_idempotent_and_ordered(monkeypatch):
    _patch(monkeypatch)
    sql = export_state.build_seed_sql()
    # tenants must precede the rows that FK-reference them
    assert sql.index("INSERT INTO tenants") < sql.index("INSERT INTO roles")
    assert sql.index("INSERT INTO tenants") < sql.index("INSERT INTO user_assignments")
    # idempotent upserts
    assert "ON CONFLICT (tenant_id) DO UPDATE" in sql
    assert "ON CONFLICT (template_id) DO UPDATE" in sql
    assert "ON CONFLICT (tenant_id, role_id) DO UPDATE" in sql
    assert "ON CONFLICT (tenant_id, scope_type, scope_id, version) DO UPDATE" in sql
    assert sql.startswith("--") and "BEGIN;" in sql and sql.rstrip().endswith("COMMIT;")


def test_seed_contains_governance_values(monkeypatch):
    _patch(monkeypatch)
    sql = export_state.build_seed_sql()
    assert "'acme-corp'" in sql and "'finance-lead'" in sql
    assert "'pat@acme-corp.example'" in sql
    assert '"max_read_classification": "confidential"' in sql  # role caps serialized as jsonb
    assert "::jsonb" in sql


def test_seed_excludes_secrets_and_sub(monkeypatch):
    _patch(monkeypatch)
    sql = export_state.build_seed_sql()
    # assignments carry only email->tenant/team/role; never the sub binding or credentials
    assert "INSERT INTO user_assignments(user_email, tenant_id, team_id, role_id)" in sql
    # check the executable body (ignore the -- comment header, which mentions "sub"/"credentials")
    body = "\n".join(ln for ln in sql.splitlines() if not ln.lstrip().startswith("--"))
    assert "sub" not in body
    assert "password" not in body.lower() and "credential" not in body.lower()
    # assignment insert is guarded (no unique key) so it's idempotent
    assert "WHERE NOT EXISTS (SELECT 1 FROM user_assignments" in body


def test_sql_escapes_quotes(monkeypatch):
    _patch(monkeypatch, {**_DATA, "tenants": [{"tenant_id": "x", "display_name": "O'Brien Inc", "region": "AC1"}]})
    sql = export_state.build_seed_sql()
    assert "O''Brien Inc" in sql  # single quote doubled, not breaking the literal


def test_latest_admin_seq(monkeypatch):
    _patch(monkeypatch)
    assert export_state.latest_admin_seq() == 42


# ---- endpoint ----
def _app():
    app = FastAPI()
    app.include_router(admin.router)
    return app


def test_export_endpoint_requires_auth():
    with TestClient(_app()) as c:
        r = c.get("/admin/export")
    assert r.status_code == 401


def test_export_endpoint_ok_with_token(monkeypatch):
    monkeypatch.setattr(admin.export_state, "build_seed_sql", lambda: "-- seed\nBEGIN;\nCOMMIT;\n")
    with TestClient(_app()) as c:
        r = c.get("/admin/export", headers={"X-Admin-Token": "change-me-admin-token"})
    assert r.status_code == 200, r.text
    assert "BEGIN;" in r.text


def test_export_endpoint_requires_platform_scope():
    app = _app()
    app.dependency_overrides[admin_principal] = lambda: AdminPrincipal(
        scope="tenant", tenant_id="acme-corp", can_edit_governance=True)
    with TestClient(app) as c:
        r = c.get("/admin/export")
    app.dependency_overrides.clear()
    assert r.status_code == 403
