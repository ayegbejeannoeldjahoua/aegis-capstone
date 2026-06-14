"""Curated governance vocabulary function + endpoint."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aegis_fabric.admin as admin
from aegis_fabric.auth import AdminPrincipal
from aegis_fabric.vocab import governance_vocab

KEYS = ["namespaces", "model_regions", "providers", "model_ids", "egress_suggestions",
        "model_purposes", "retention_classes", "runtime_languages", "dual_control_actions"]


def test_vocab_function_shape_and_sources():
    v = governance_vocab()
    for k in KEYS:
        assert k in v and isinstance(v[k], list), k
    # namespaces: base set present
    assert {"analyst-notes", "team-decisions"} <= set(v["namespaces"])
    # dynamic from the model registry
    assert "openai" in v["providers"] and "anthropic" in v["providers"]
    assert "openai/gpt-4.1" in v["model_ids"] and "anthropic/claude-sonnet-4-6" in v["model_ids"]
    assert "AC1" in v["model_regions"]
    # static enums
    assert set(v["model_purposes"]) == {"chat", "embedding", "vision", "code"}
    assert "tenant.delete" in v["dual_control_actions"]
    assert "*" in v["egress_suggestions"]


def test_admin_vocab_endpoint():
    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.admin_principal] = lambda: AdminPrincipal(scope="platform", tenant_id=None)
    with TestClient(app) as c:
        r = c.get("/admin/vocab")
    assert r.status_code == 200
    body = r.json()
    assert "namespaces" in body and "providers" in body and "model_purposes" in body
