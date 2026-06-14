"""v1.20 -- regression guards for the two governance pull-forwards:

  BR-ISO-05 (RLS backstop): migration 0007_rls.sql enables RLS on the four
  per-tenant data tables and adds a tenant-isolation policy keyed on the
  per-connection `app.tenant_id` GUC. The db.with_tenant_scope() helper sets
  that GUC so the application code path through the connection pool is RLS-
  aware. We can't run live Postgres here, but we can verify the migration
  text + that the helper is wired and behaves correctly with a fake conn.

  BR-CAP-02 (sensitive-action re-auth): the new
  sensitive_action_max_age_minutes setting + require_recent_auth helper +
  recently_authenticated_principal FastAPI dependency together force a
  re-login when a token is older than the freshness window, even when the
  underlying session is still valid.
"""
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

import aegis_fabric.auth as auth_mod
import aegis_fabric.db as db_mod
import aegis_fabric.settings as settings_mod
from aegis_fabric.auth import Subject, require_recent_auth

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# BR-ISO-05: RLS migration + db helper
# ---------------------------------------------------------------------------

def test_rls_migration_enables_and_forces_rls_on_all_four_tables():
    sql = (ROOT / "deploy" / "postgres" / "migrations" / "0007_rls.sql").read_text()
    for tbl in ["memories", "sessions", "audit_events", "isas"]:
        assert f"ALTER TABLE {tbl}" in sql and "ENABLE ROW LEVEL SECURITY" in sql
        # FORCE makes RLS apply to table owners too (without it the app role bypasses RLS).
        assert f"ALTER TABLE {tbl}" in sql and "FORCE  ROW LEVEL SECURITY" in sql


def test_rls_policies_use_tenant_id_guc_with_bypass_marker():
    sql = (ROOT / "deploy" / "postgres" / "migrations" / "0007_rls.sql").read_text()
    # Each table must have a policy that reads app.tenant_id and treats '*' as bypass.
    for tbl in ["memories", "sessions", "audit_events", "isas"]:
        assert f"CREATE POLICY tenant_isolation_{tbl} ON {tbl}" in sql
    assert sql.count("current_setting('app.tenant_id', true) IN (tenant_id, '*')") >= 8  # USING + WITH CHECK x 4 tables


def test_with_tenant_scope_sets_guc_and_commits(monkeypatch):
    """The helper must call set_config('app.tenant_id', ...) on the borrowed
    connection. If the caller raises, the transaction must be rolled back."""
    set_config_calls = []
    commits = []
    rollbacks = []

    class FakeConn:
        def execute(self, sql, params=()):
            if "set_config" in sql:
                set_config_calls.append(params[0])
        def commit(self):
            commits.append(True)
        def rollback(self):
            rollbacks.append(True)

    class FakePool:
        def connection(self):
            class _Mgr:
                def __enter__(_): return FakeConn()
                def __exit__(_, *a): return False
            return _Mgr()

    monkeypatch.setattr(db_mod, "get_pool", lambda: FakePool())

    with db_mod.with_tenant_scope("acme-corp"):
        pass
    assert set_config_calls == ["acme-corp"]
    assert commits == [True] and rollbacks == []

    set_config_calls.clear()
    commits.clear()
    with pytest.raises(RuntimeError):
        with db_mod.with_tenant_scope(None):  # None -> BYPASS_TENANT
            raise RuntimeError("boom")
    assert set_config_calls == [db_mod.BYPASS_TENANT]
    assert rollbacks == [True]


def test_bypass_constant_is_star():
    assert db_mod.BYPASS_TENANT == "*"


# ---------------------------------------------------------------------------
# BR-CAP-02: sensitive-action re-auth
# ---------------------------------------------------------------------------

def _mk_subject(iat_offset_seconds: int = 0) -> Subject:
    """Build a Subject whose token claims have iat = now + offset."""
    iat = time.time() + iat_offset_seconds
    return Subject(
        sub="u1", email="u1@acme.example", tenant_id="acme-corp",
        team_id="research", role="analyst", groups=[],
        token_claims={"iat": iat, "sub": "u1"},
    )


def test_recent_auth_passes_for_fresh_token():
    subj = _mk_subject(iat_offset_seconds=-60)  # 1 minute old
    # Window is 30 minutes -> 1 minute is well under -> no raise
    require_recent_auth(subj, max_age_minutes=30)


def test_recent_auth_rejects_old_token():
    subj = _mk_subject(iat_offset_seconds=-60 * 60)  # 1 hour old
    with pytest.raises(HTTPException) as exc:
        require_recent_auth(subj, max_age_minutes=30)
    assert exc.value.status_code == 401
    assert "re-authentication required" in exc.value.detail.lower()


def test_recent_auth_rejects_missing_iat_claim():
    subj = Subject(sub="u1", email="u@x", tenant_id="t", team_id="r",
                   role="analyst", groups=[], token_claims={"sub": "u1"})
    with pytest.raises(HTTPException) as exc:
        require_recent_auth(subj, max_age_minutes=30)
    assert exc.value.status_code == 401
    assert "iat" in exc.value.detail.lower()


def test_recent_auth_zero_window_disables_check():
    """sensitive_action_max_age_minutes=0 must disable the check (test/debug
    escape hatch), regardless of token age."""
    subj = _mk_subject(iat_offset_seconds=-99999)
    require_recent_auth(subj, max_age_minutes=0)  # no raise


def test_settings_default_is_30_minutes():
    assert settings_mod.settings.sensitive_action_max_age_minutes == 30


def test_recent_auth_uses_settings_default(monkeypatch):
    """When max_age_minutes is None, the helper reads from settings."""
    monkeypatch.setattr(settings_mod.settings, "sensitive_action_max_age_minutes", 5)
    subj_fresh = _mk_subject(iat_offset_seconds=-60)
    require_recent_auth(subj_fresh)  # 1 min old, 5 min window -> ok

    subj_old = _mk_subject(iat_offset_seconds=-10 * 60)
    with pytest.raises(HTTPException):
        require_recent_auth(subj_old)  # 10 min old, 5 min window -> 401


def test_recently_authenticated_principal_dependency_exists():
    """The FastAPI dependency must be exported and callable."""
    assert callable(auth_mod.recently_authenticated_principal)
