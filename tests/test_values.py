import aegis_fabric.rbac as rbac
import aegis_fabric.values as values_mod
from aegis_fabric.values import resolve_values

ANALYST = {**rbac.EMPTY_CAPS, "skills": ["summarise-with-memory"], "tools": ["external_lookup"],
           "readable_namespaces": ["analyst-notes"], "writable_namespaces": ["analyst-notes"],
           "allowed_model_regions": ["AC1"], "max_summary_words": 200, "runtime_exec": False}


def _stub(monkeypatch, caps, rules=None):
    monkeypatch.setattr(values_mod, "role_capabilities", lambda t, r: dict(caps))
    monkeypatch.setattr(values_mod, "_load_rules", lambda *a, **k: {"rules": rules or {}, "versions": {}})
    monkeypatch.setattr(values_mod.platform_settings, "get_default_model", lambda: None)


def test_caps_flow_into_values(monkeypatch):
    _stub(monkeypatch, ANALYST)
    v = resolve_values("acme", "research", "analyst", "jane@acme")
    assert v.skills == ["summarise-with-memory"]
    assert v.writable_namespaces == ["analyst-notes"]
    assert v.allowed_model_region == "AC1"
    assert v.runtime_exec is False


def test_summary_narrowing(monkeypatch):
    _stub(monkeypatch, ANALYST, rules={"individual": {"preferred_summary_words": 100}})
    assert resolve_values("acme", "research", "analyst", "j").summary_words == 100
    assert resolve_values("acme", "research", "analyst", "j", 50).summary_words == 50
    assert resolve_values("acme", "research", "analyst", "j", 9999).summary_words == 100


def test_viewer_has_no_skills_or_writes(monkeypatch):
    viewer = {**rbac.EMPTY_CAPS, "readable_namespaces": ["analyst-notes"], "allowed_model_regions": ["AC1"], "max_summary_words": 200}
    _stub(monkeypatch, viewer)
    v = resolve_values("acme", "research", "viewer", "v@acme")
    assert v.skills == [] and v.writable_namespaces == []


def _caps_full(**over):
    base = {**rbac.EMPTY_CAPS, "skills": [], "tools": [], "readable_namespaces": [],
            "writable_namespaces": [], "allowed_model_regions": ["AC1"], "max_summary_words": 200}
    base.update(over)
    return base


def test_values_tighten_caps(monkeypatch):
    """org/team VALUES tighten role caps; team beats org when stricter; trace is recorded."""
    caps = _caps_full(max_output_tokens=4096, max_read_classification="restricted",
                      write_requires_approval_above="restricted", residency_strict=False,
                      token_budget_per_day=0)
    rules = {"org": {"max_output_tokens": 2048, "max_read_classification": "confidential",
                     "write_requires_approval_above": "internal", "token_budget_per_day": 500000,
                     "residency_strict": True},
             "team": {"max_output_tokens": 1024}}
    _stub(monkeypatch, caps, rules=rules)
    v = resolve_values("acme", "research", "lead", "u@acme")
    assert v.max_output_tokens == 1024                      # team (1024) beat org (2048)
    assert v.max_read_classification == "confidential"      # org lowered the ceiling from restricted
    assert "confidential" in v.readable_classifications and "restricted" not in v.readable_classifications
    assert v.write_requires_approval_above == "internal"
    assert v.token_budget_per_day == 500000                 # org set a positive cap (was 0 = unlimited)
    assert v.residency_strict is True
    fields = {(o["scope"], o["field"]) for o in v.values_overlay}
    assert ("team", "max_output_tokens") in fields and ("org", "max_read_classification") in fields


def test_values_cannot_widen(monkeypatch):
    """Defense in depth: values looser than the role's caps are ignored (never widen)."""
    caps = _caps_full(max_output_tokens=1024, max_read_classification="internal",
                      write_requires_approval_above="internal", token_budget_per_day=1000)
    rules = {"org": {"max_output_tokens": 8192, "max_read_classification": "restricted",
                     "write_requires_approval_above": "restricted", "token_budget_per_day": 999999}}
    _stub(monkeypatch, caps, rules=rules)
    v = resolve_values("acme", "research", "analyst", "u@acme")
    assert v.max_output_tokens == 1024
    assert v.max_read_classification == "internal"
    assert v.write_requires_approval_above == "internal"
    assert v.token_budget_per_day == 1000
    assert v.values_overlay == []
