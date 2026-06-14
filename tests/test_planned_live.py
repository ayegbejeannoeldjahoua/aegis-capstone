"""v1.10.0 — the remaining 'planned' capabilities made live: input-token gate,
fallback_mode/residency_strict, concurrency, runtime_network gate, audit scope,
and the ops-admin endpoints (traces/signing-keys/secrets/skills-register/impersonate)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aegis_fabric.admin as admin
import aegis_fabric.audit as audit
import aegis_fabric.rbac as rbac
from aegis_fabric.auth import AdminPrincipal
from aegis_fabric.usage import UsageLimiter


# ---- concurrency ----
def test_concurrency_slots():
    u = UsageLimiter()
    assert u.acquire_slot("acme", "s", 2) is True
    assert u.acquire_slot("acme", "s", 2) is True
    assert u.acquire_slot("acme", "s", 2) is False   # 3rd over the cap of 2
    u.release_slot("acme", "s", 2)
    assert u.acquire_slot("acme", "s", 2) is True     # a slot freed
    assert u.acquire_slot("acme", "s", 0) is True     # 0 = unlimited


# ---- fallback_mode / residency_strict drop the fallback chain ----
def test_fallback_mode_strict(tmp_path, monkeypatch):
    """Build a registry WITH a fallback chain (the production registry ships none in v1.15.0) and
    confirm fallback_mode=strict / residency_strict truncate the candidate list to the primary."""
    import textwrap

    from aegis_fabric.models import ModelRegistry
    monkeypatch.setenv("OPENAI_BASE_URL", "http://op/v1")
    cfg = tmp_path / "reg.yaml"
    cfg.write_text(textwrap.dedent("""
        version: 1
        selection: {default_model: openai/a, fallbacks: [openai/b]}
        providers:
          openai:
            type: openai_compatible
            base_url_env: OPENAI_BASE_URL
            region: AC1
            local: false
            models:
              - {id: openai/a, supports_tools: true}
              - {id: openai/b, supports_tools: true}
    """))
    reg = ModelRegistry(path=str(cfg))
    multi = reg.route(None, allowed_region="AC1", caps={})
    one = reg.route(None, allowed_region="AC1", caps={"fallback_mode": "strict"})
    res = reg.route(None, allowed_region="AC1", caps={"residency_strict": True})
    assert len(multi) > 1
    assert len(one) == 1 and len(res) == 1


# ---- input-token + runtime_network gate logic (mirrors sentinel.rego vs caps) ----
def _caps(role):
    return rbac.derived_caps(rbac.template_capabilities(role))


def test_input_token_gate():
    c = _caps("analyst")  # max_input_tokens default 8192
    assert (100 <= c["max_input_tokens"]) is True
    assert (9000 <= c["max_input_tokens"]) is False


def test_runtime_network_gate():
    c = _caps("lead")  # runtime_network default "none"
    def ok(network):
        return network == "none" or network == c["runtime_network"]
    assert ok("none") is True
    assert ok("bridge") is False


# ---- audit scope clauses ----
def test_audit_scope_clauses():
    own, _ = audit._scope_clauses("acme", "own", "jane@acme")
    ten, _ = audit._scope_clauses("acme", "tenant", "jane@acme")
    alls, ap = audit._scope_clauses("acme", "all", "jane@acme")
    assert own == ["tenant_id=%s", "subject=%s"]
    assert ten == ["tenant_id=%s"]
    assert alls == [] and ap == []


# ---- ops-admin endpoints ----
def _app(principal, monkeypatch):
    async def fake_run_db(fn, *a, **k):
        return fn(*a, **k)
    monkeypatch.setattr(admin, "run_db", fake_run_db)
    monkeypatch.setattr(admin, "_audit_admin", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.admin_principal] = lambda: principal
    return app


def test_signing_keys_gated(monkeypatch):
    yes = AdminPrincipal(scope="platform", can_manage_signing_keys=True)
    no = AdminPrincipal(scope="tenant", tenant_id="acme-corp")
    with TestClient(_app(yes, monkeypatch)) as c:
        r = c.get("/admin/signing-keys")
        assert r.status_code == 200 and r.json()["algorithm"] == "ed25519" and r.json()["public_key"]
    with TestClient(_app(no, monkeypatch)) as c:
        assert c.get("/admin/signing-keys").status_code == 403


def test_traces_gated(monkeypatch):
    monkeypatch.setattr(audit, "recent_traces", lambda *a, **k: [{"trace_id": "t1", "events": 5}])
    yes = AdminPrincipal(scope="platform", can_view_traces=True)
    with TestClient(_app(yes, monkeypatch)) as c:
        r = c.get("/admin/traces")
        assert r.status_code == 200 and r.json()["traces"][0]["trace_id"] == "t1"
    with TestClient(_app(AdminPrincipal(scope="tenant", tenant_id="acme-corp"), monkeypatch)) as c:
        assert c.get("/admin/traces").status_code == 403


def test_secret_rotate_direct_and_dualcontrol(monkeypatch):
    direct = AdminPrincipal(scope="platform", can_rotate_secrets=True, dual_control_actions=[])
    with TestClient(_app(direct, monkeypatch)) as c:
        r = c.post("/admin/secrets/rotate", json={"name": "x"})
        assert r.status_code == 200 and r.json()["rotated"] is True
    monkeypatch.setattr(admin.approvals, "create_pending", lambda *a, **k: {"pending": True})
    dc = AdminPrincipal(scope="platform", can_rotate_secrets=True, dual_control_actions=["secret.rotate"])
    with TestClient(_app(dc, monkeypatch)) as c:
        assert c.post("/admin/secrets/rotate", json={"name": "x"}).json()["pending"] is True
    with TestClient(_app(AdminPrincipal(scope="platform"), monkeypatch)) as c:
        assert c.post("/admin/secrets/rotate", json={"name": "x"}).status_code == 403


def test_skill_register_validates_signature(monkeypatch):
    import yaml
    manifest = yaml.safe_load(open("configs/skills/assistant.skill.yaml").read())
    pa = AdminPrincipal(scope="platform", can_register_skills=True)
    with TestClient(_app(pa, monkeypatch)) as c:
        r = c.post("/admin/skills/register", json={"manifest": manifest})
        assert r.status_code == 200 and r.json()["signature_valid"] is True and r.json()["accepted"] is True
        bad = c.post("/admin/skills/register", json={"manifest": {"skill_id": "x"}})
        assert bad.json()["signature_valid"] is False


def test_impersonate_read_only(monkeypatch):
    monkeypatch.setattr(admin, "_impersonate_context",
                        lambda email, tf: {"email": email, "role_id": "analyst", "capabilities": {}})
    yes = AdminPrincipal(scope="platform", can_impersonate="full")
    with TestClient(_app(yes, monkeypatch)) as c:
        r = c.post("/admin/impersonate", json={"email": "jane@acme-corp.example"})
        assert r.status_code == 200 and r.json()["role_id"] == "analyst"
    with TestClient(_app(AdminPrincipal(scope="platform", can_impersonate="none"), monkeypatch)) as c:
        assert c.post("/admin/impersonate", json={"email": "x@y.z"}).status_code == 403
