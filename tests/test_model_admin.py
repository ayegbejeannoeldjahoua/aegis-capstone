"""Platform global-model selection (/admin/model) + routing override.

The platform admin picks one model that serves everyone; the choice is stored in
platform_settings and flows into routing as the effective default. A model is only
eligible. Model risk-tier gating was removed in v1.15.0 — any registered model can be the
global default. platform_settings is faked and the real model registry is used."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import aegis_fabric.admin as admin
from aegis_fabric.auth import AdminPrincipal, admin_principal
from aegis_fabric.models import registry


@pytest.fixture
def memstore(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(admin.platform_settings, "get_default_model", lambda: store.get("default_model"))
    monkeypatch.setattr(admin.platform_settings, "set_default_model",
                        lambda mid, actor="x": store.__setitem__("default_model", mid))
    monkeypatch.setattr(admin, "_audit_admin", lambda *a, **k: None)
    return store


def test_set_default_known_model(memstore):
    out = admin._set_default_model(admin.DefaultModel(model_id="nvidia/nemotron-3-super-120b-a12b"), "pat")
    assert out["active_model"] == "nvidia/nemotron-3-super-120b-a12b"
    assert out["selected"] == "nvidia/nemotron-3-super-120b-a12b" and out["source"] == "platform"
    assert any(m["active"] and m["model_id"] == "nvidia/nemotron-3-super-120b-a12b" for m in out["models"])


def test_set_default_unknown_model(memstore):
    with pytest.raises(ValueError) as e:
        admin._set_default_model(admin.DefaultModel(model_id="ollama/nope:1b"), "pat")
    assert str(e.value) == "unknown_model"


def test_set_default_allows_any_model(memstore):
    # v1.15.0: no risk-tier ceiling — any registered model can be set as the global default.
    out = admin._set_default_model(admin.DefaultModel(model_id="anthropic/claude-sonnet-4-6"), "pat")
    assert out["active_model"] == "anthropic/claude-sonnet-4-6"
    assert all(m["serves_everyone"] for m in out["models"])


def test_model_view_defaults_to_registry(memstore):
    v = admin._model_view()
    assert v["source"] == "registry"
    assert v["active_model"] == registry.default_model_id() == "openai/gpt-4.1"
    assert len(v["models"]) == 3 and all(m["serves_everyone"] for m in v["models"])


def test_default_model_id_validation():
    with pytest.raises(ValidationError):
        admin.DefaultModel(model_id="")


def test_route_registry_default_is_gpt41_for_viewer():
    cands = registry.route(None, allowed_region="AC1", classification="internal",
                           caps={"max_model_risk_tier": "T2"})
    assert cands[0].model_id == "openai/gpt-4.1"


def test_route_honours_explicit_global_default():
    cands = registry.route(None, allowed_region="AC1", classification="internal",
                           default_model="nvidia/nemotron-3-super-120b-a12b", caps={"max_model_risk_tier": "T2"})
    assert cands[0].model_id == "nvidia/nemotron-3-super-120b-a12b"


def _app():
    app = FastAPI()
    app.include_router(admin.router)
    return app


def test_model_endpoint_requires_auth():
    with TestClient(_app()) as c:
        r = c.get("/admin/model")
    assert r.status_code == 401


def test_model_get_ok_with_token(monkeypatch):
    monkeypatch.setattr(admin, "_model_view", lambda: {"active_model": "openai/gpt-4.1", "models": []})
    with TestClient(_app()) as c:
        r = c.get("/admin/model", headers={"X-Admin-Token": "change-me-admin-token"})
    assert r.status_code == 200, r.text
    assert r.json()["active_model"] == "openai/gpt-4.1"


def test_model_put_ok_with_token(monkeypatch):
    monkeypatch.setattr(admin, "_set_default_model", lambda p, actor: {"active_model": p.model_id, "models": []})
    with TestClient(_app()) as c:
        r = c.put("/admin/model", headers={"X-Admin-Token": "change-me-admin-token"},
                  json={"model_id": "nvidia/nemotron-3-super-120b-a12b"})
    assert r.status_code == 200, r.text
    assert r.json()["active_model"] == "nvidia/nemotron-3-super-120b-a12b"


def test_model_put_unknown_maps_400(monkeypatch):
    def _raise(p, actor):
        raise ValueError("unknown_model")
    monkeypatch.setattr(admin, "_set_default_model", _raise)
    with TestClient(_app()) as c:
        r = c.put("/admin/model", headers={"X-Admin-Token": "change-me-admin-token"}, json={"model_id": "x/y"})
    assert r.status_code == 400


def test_model_endpoint_requires_platform_scope():
    app = _app()
    app.dependency_overrides[admin_principal] = lambda: AdminPrincipal(
        scope="tenant", tenant_id="acme-corp", can_edit_governance=True)
    with TestClient(app) as c:
        r = c.get("/admin/model")
    app.dependency_overrides.clear()
    assert r.status_code == 403
