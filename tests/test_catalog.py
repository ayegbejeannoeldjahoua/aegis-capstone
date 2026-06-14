"""Skills/tools catalog: helper functions + the read-only endpoints."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aegis_fabric.admin as admin
import aegis_fabric.main as main
from aegis_fabric import tools
from aegis_fabric.auth import AdminPrincipal, Subject, get_subject
from aegis_fabric.skills import SkillRegistry


def test_skill_catalog_function():
    cat = SkillRegistry("configs/skills").catalog()
    assert len(cat) == 18
    assert all(c["signed"] for c in cat)
    one = next(c for c in cat if c["skill_id"] == "invoice-extract")
    assert one["risk_tier"] and "pdf_extract" in one["tools"]


def test_tool_catalog_function():
    cat = tools.catalog()
    ids = {c["tool_id"] for c in cat}
    assert {"calculator", "web_fetch", "email_send"} <= ids
    by = {c["tool_id"]: c for c in cat}
    assert by["calculator"]["egress"] == "none"
    assert by["web_fetch"]["egress"] == "allowlist"
    assert by["db_query"]["pii"] == "high"


def test_v1_catalog_endpoints(monkeypatch):
    subject = Subject(sub="s", email="jane@acme-corp.example", tenant_id="acme-corp",
                      team_id="research", role="analyst", token_claims={})
    main.app.dependency_overrides[get_subject] = lambda: subject
    monkeypatch.setattr(main.limiter, "allow", lambda *a, **k: True)
    try:
        c = TestClient(main.app)
        rs = c.get("/v1/skills")
        rt = c.get("/v1/tools")
        assert rs.status_code == 200 and len(rs.json()["skills"]) == 18
        assert rt.status_code == 200 and len(rt.json()["tools"]) >= 16
    finally:
        main.app.dependency_overrides.clear()


def test_admin_catalog_endpoints():
    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.admin_principal] = lambda: AdminPrincipal(scope="platform", tenant_id=None)
    with TestClient(app) as c:
        assert c.get("/admin/skills").json()["skills"][0]["skill_id"]
        assert c.get("/admin/tools").json()["tools"][0]["tool_id"]


def test_v1_skills_requires_auth():
    c = TestClient(main.app)  # no context manager -> no lifespan/DB
    assert c.get("/v1/skills").status_code == 401
