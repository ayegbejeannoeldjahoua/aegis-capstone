import textwrap

import pytest

from aegis_fabric.models import ModelNotAllowed, ModelRegistry


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://openai/v1")
    monkeypatch.setenv("NVIDIA_BASE_URL", "http://nvidia/v1")
    yaml_text = textwrap.dedent(
        """
        version: 1
        selection:
          default_model: ollama/llama3.1:8b
          fallbacks: [openai/gpt-4.1-mini]
        providers:
          ollama:
            type: ollama
            base_url_env: OLLAMA_BASE_URL
            region: AC1
            local: true
            models:
              - id: ollama/llama3.1:8b
                aliases: [local-fast]
                supports_tools: false
          openai:
            type: openai_compatible
            base_url_env: OPENAI_BASE_URL
            region: AC1
            local: false
            models:
              - id: openai/gpt-4.1-mini
                supports_tools: true
          nvidia:
            type: openai_compatible
            base_url_env: NVIDIA_BASE_URL
            region: EU1
            local: false
            models:
              - id: nvidia/nemotron
                supports_tools: true
        routing_policies:
          - name: local-only-for-restricted
            when: {classification_in: [restricted, confidential]}
            require: {local: true}
        """
    )
    p = tmp_path / "model_registry.yaml"
    p.write_text(yaml_text)
    return ModelRegistry(path=str(p))


def test_resolve_unknown_raises(registry):
    with pytest.raises(ModelNotAllowed):
        registry.resolve("does/not-exist")


def test_alias_resolution(registry):
    assert registry.resolve("local-fast").model_id == "ollama/llama3.1:8b"


def test_route_region_residency_excludes_wrong_region(registry):
    profiles = registry.route(None, allowed_region="AC1")
    ids = [p.model_id for p in profiles]
    assert "nvidia/nemotron" not in ids  # EU1 filtered out
    assert profiles[0].region == "AC1"


def test_route_restricted_data_requires_local(registry):
    profiles = registry.route(None, allowed_region="AC1", classification="restricted")
    assert all(p.local for p in profiles)
    assert profiles[0].model_id == "ollama/llama3.1:8b"


def test_route_includes_fallbacks_in_order(registry):
    profiles = registry.route("local-fast", allowed_region="AC1")
    ids = [p.model_id for p in profiles]
    assert ids[0] == "ollama/llama3.1:8b"
    assert "openai/gpt-4.1-mini" in ids


def test_pinned_model_violating_region_raises(registry):
    with pytest.raises(ModelNotAllowed):
        registry.route("nvidia/nemotron", allowed_region="AC1")


def test_tool_support_requirement(registry):
    profiles = registry.route(None, allowed_region="AC1", require_tool_support=True)
    assert all(p.supports_tools for p in profiles)


@pytest.fixture
def gov_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://o")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://op")
    yaml_text = textwrap.dedent(
        """
        version: 1
        selection: {default_model: ollama/local, fallbacks: [openai/hosted]}
        providers:
          ollama:
            type: ollama
            base_url_env: OLLAMA_BASE_URL
            region: AC1
            local: true
            models: [{id: ollama/local, risk_tiers: [T1, T2]}]
          openai:
            type: openai_compatible
            base_url_env: OPENAI_BASE_URL
            region: AC1
            local: false
            models: [{id: openai/hosted, supports_tools: true, risk_tiers: [T1, T2, T3]}]
        routing_policies:
          - {name: local-only-for-restricted, when: {classification_in: [restricted]}, require: {local: true}}
        """
    )
    p = tmp_path / "reg.yaml"
    p.write_text(yaml_text)
    return ModelRegistry(path=str(p))


def test_route_provider_allowlist(gov_registry):
    profs = gov_registry.route(None, allowed_region="AC1", caps={"allowed_providers": ["ollama"]})
    assert all(p.provider == "ollama" for p in profs)


def test_route_model_id_allowlist(gov_registry):
    profs = gov_registry.route(None, allowed_region="AC1", caps={"allowed_model_ids": ["openai/hosted"]})
    assert [p.model_id for p in profs] == ["openai/hosted"]


def test_route_max_risk_tier_no_longer_excludes(gov_registry):
    """v1.15.0: model risk-tier gating was removed. A role's max_model_risk_tier no longer
    excludes any model from routing — both the T2 local model and the T3 hosted model route."""
    profs = gov_registry.route(None, allowed_region="AC1", caps={"max_model_risk_tier": "T2"})
    ids = [p.model_id for p in profs]
    assert "ollama/local" in ids and "openai/hosted" in ids


def test_route_local_above_classification(gov_registry):
    conf = gov_registry.route(None, allowed_region="AC1", classification="confidential",
                              caps={"require_local_above_classification": "confidential"})
    assert all(p.local for p in conf)
    internal = gov_registry.route(None, allowed_region="AC1", classification="internal",
                                  caps={"require_local_above_classification": "confidential"})
    assert any(not p.local for p in internal)


def test_viewer_template_can_route(monkeypatch):
    """Regression (v1.11.4): every standard template must route to >=1 model.

    The viewer template shipped with max_model_risk_tier=T1, but every model in
    the real registry computes to an effective tier >=T2 (the local 8B is
    [T1,T2] -> max T2), so a T1 ceiling left ZERO routable models and silently
    broke chat for all viewer-derived roles (legal-viewer, support-viewer) with
    'no model satisfies routing policy'. Guard against a T1 (or other unroutable)
    regression on the shared templates."""
    from pathlib import Path

    from aegis_fabric import rbac

    for var in ("OLLAMA_BASE_URL", "OPENAI_BASE_URL", "NVIDIA_BASE_URL", "VLLM_BASE_URL"):
        monkeypatch.setenv(var, "http://stub/v1")
    cfg = Path(__file__).resolve().parents[1] / "configs" / "model_registry.yaml"
    assert cfg.exists(), cfg
    reg = ModelRegistry(path=str(cfg))
    for tmpl in ("viewer", "analyst", "lead", "tenant-admin", "platform-admin"):
        caps = rbac.template_capabilities(tmpl)
        cands = reg.route(None, allowed_region="AC1", classification="internal", caps=caps)
        assert cands, f"{tmpl} template must route to at least one model (got none)"


def test_viewer_template_tier_at_least_t2():
    """The viewer ceiling must clear the lowest model tier present in the registry."""
    from aegis_fabric import rbac

    caps = rbac.template_capabilities("viewer")
    assert rbac.RISK_RANK[caps["max_model_risk_tier"]] >= rbac.RISK_RANK["T2"]


def test_three_hosted_models_registered_and_default_is_gpt41(monkeypatch):
    """v1.15.0: exactly three hosted models are registered (no local/Ollama); the global default
    is openai/gpt-4.1; the anthropic provider resolves to type 'anthropic'; and the default routes
    for a viewer-ceiling role (model tiers are no longer enforced)."""
    from pathlib import Path

    for var in ("OPENAI_BASE_URL", "NVIDIA_BASE_URL", "ANTHROPIC_BASE_URL"):
        monkeypatch.setenv(var, "http://stub/v1")
    cfg = Path(__file__).resolve().parents[1] / "configs" / "model_registry.yaml"
    reg = ModelRegistry(path=str(cfg))
    ids = {m["id"] for p in reg.raw["providers"].values() for m in p["models"]}
    assert ids == {"openai/gpt-4.1", "nvidia/nemotron-3-super-120b-a12b", "anthropic/claude-sonnet-4-6"}
    assert "ollama" not in reg.raw["providers"]
    assert reg._selection().get("default_model") == "openai/gpt-4.1"
    assert reg.resolve("anthropic/claude-sonnet-4-6").type == "anthropic"
    assert reg.resolve("claude").model_id == "anthropic/claude-sonnet-4-6"  # alias
    cands = reg.route(None, allowed_region="AC1", classification="internal",
                      caps={"max_model_risk_tier": "T2"})
    assert cands[0].model_id == "openai/gpt-4.1"  # default routes for every role


def test_hosted_only_routes_restricted_data(monkeypatch):
    """With no local provider registered, the 'restricted data must be local' rule is vacuous:
    restricted/confidential classifications route to hosted models (governed by per-role
    classification ceilings instead of model residency)."""
    from pathlib import Path

    for var in ("OPENAI_BASE_URL", "NVIDIA_BASE_URL", "ANTHROPIC_BASE_URL"):
        monkeypatch.setenv(var, "http://stub/v1")
    cfg = Path(__file__).resolve().parents[1] / "configs" / "model_registry.yaml"
    reg = ModelRegistry(path=str(cfg))
    cands = reg.route(None, allowed_region="AC1", classification="restricted",
                      caps={"require_local_above_classification": "restricted"})
    assert cands and cands[0].model_id == "openai/gpt-4.1"
