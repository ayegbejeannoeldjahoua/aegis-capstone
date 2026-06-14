from aegis_fabric.auth import Subject
from aegis_fabric.policy import _fallback, _valid_tenant
from aegis_fabric.values import ResolvedValues


def _subject(tenant="acme", role="analyst"):
    return Subject(sub="s", email="j@acme", tenant_id=tenant, team_id="research", role=role, token_claims={})


def _vals(**over):
    base = dict(tenant_id="acme", team_id="research", role="analyst", user="j@acme",
                skills=["summarise-with-memory"], allowed_tools=["external_lookup"],
                readable_namespaces=["analyst-notes"], writable_namespaces=["analyst-notes"],
                allowed_model_regions=["AC1"], allowed_model_region="AC1", runtime_exec=False)
    base.update(over)
    return ResolvedValues(**base)


def test_cross_tenant_resource_denied():
    s = _subject("acme")
    res = {"tenant_id": "beta", "namespace": "analyst-notes"}
    assert _fallback("memory.read", res, _vals(), s)["allow"] is False
    assert not _valid_tenant(res, s)


def test_same_tenant_read_allowed():
    assert _fallback("memory.read", {"tenant_id": "acme", "namespace": "analyst-notes"}, _vals(), _subject())["allow"] is True


def test_analyst_cannot_write_team_decisions():
    out = _fallback("memory.write", {"tenant_id": "acme", "namespace": "team-decisions"}, _vals(), _subject())
    assert out["allow"] is False


def test_lead_can_write_team_decisions():
    v = _vals(writable_namespaces=["analyst-notes", "team-decisions"])
    assert _fallback("memory.write", {"tenant_id": "acme", "namespace": "team-decisions"}, v, _subject(role="lead"))["allow"] is True


def test_model_region_enforced():
    assert _fallback("model.call", {"tenant_id": "acme", "region": "AC1"}, _vals(), _subject())["allow"] is True
    assert _fallback("model.call", {"tenant_id": "acme", "region": "EU1"}, _vals(), _subject())["allow"] is False


def test_skill_requires_capability():
    out = _fallback("skill.invoke", {"tenant_id": "acme", "skill_id": "summarise-with-memory"}, _vals(skills=[]), _subject(role="viewer"))
    assert out["allow"] is False


def test_runtime_requires_flag():
    assert _fallback("runtime.exec", {"tenant_id": "acme", "network": "none"}, _vals(runtime_exec=True), _subject())["allow"] is True
    assert _fallback("runtime.exec", {"tenant_id": "acme", "network": "none"}, _vals(runtime_exec=False), _subject())["allow"] is False


def test_write_above_max_classification_denied():
    v = _vals(writable_namespaces=["analyst-notes"], writable_classifications=["public", "internal"])
    res = {"tenant_id": "acme", "namespace": "analyst-notes", "classification": "restricted"}
    out = _fallback("memory.write", res, v, _subject())
    assert out["allow"] is False


def test_write_within_classification_allowed():
    v = _vals(writable_namespaces=["analyst-notes"], writable_classifications=["public", "internal"])
    res = {"tenant_id": "acme", "namespace": "analyst-notes", "classification": "internal"}
    assert _fallback("memory.write", res, v, _subject())["allow"] is True


def test_model_provider_allowlist_denied():
    v = _vals(allowed_providers=["ollama"])
    res = {"tenant_id": "acme", "region": "AC1", "provider": "openai"}
    assert _fallback("model.call", res, v, _subject())["allow"] is False


def test_model_provider_allowlist_allowed():
    v = _vals(allowed_providers=["ollama"])
    res = {"tenant_id": "acme", "region": "AC1", "provider": "ollama"}
    assert _fallback("model.call", res, v, _subject())["allow"] is True
