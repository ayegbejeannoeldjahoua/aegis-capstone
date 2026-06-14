"""The chat assistant injects a 'governance profile' into its system prompt so it can truthfully
answer the logged-in user's questions about their own capabilities/values (v1.17.0)."""
from aegis_fabric.skill_runner import _governance_profile
from aegis_fabric.values import ResolvedValues


def test_governance_profile_summarizes_caps_and_overlay():
    v = ResolvedValues(
        tenant_id="acme-corp", team_id="markets", role="lead", user="lee@acme-corp.example",
        allowed_tools=["doc_search", "calculator"], skills=["assistant"],
        max_read_classification="confidential", max_write_classification="confidential",
        pii_scope="full", max_output_tokens=1024, token_budget_per_day=50000,
        write_requires_approval_above="public", admin_scope="none", audit_scope="team",
        runtime_exec=True, residency_strict=True,
        values_overlay=[{"scope": "team", "field": "max_output_tokens", "value": 1024}],
    )
    text = _governance_profile(v)
    assert "role=lead" in text and "team=markets" in text and "lee@acme-corp.example" in text
    assert "doc_search, calculator" in text and "Skills granted: assistant" in text
    assert "read up to 'confidential'" in text and "PII scope=full" in text
    assert "max output tokens=1024" in text and "daily token budget=50000" in text
    assert "writes above classification 'public'" in text
    assert "max_output_tokens -> 1024 (from team values)" in text


def test_governance_profile_unlimited_budget_and_no_overlay():
    v = ResolvedValues(tenant_id="beta-corp", team_id="research", role="lead", user="fin@beta",
                       token_budget_per_day=0, values_overlay=[])
    text = _governance_profile(v)
    assert "daily token budget=unlimited" in text
    assert "Tools allowed: none" in text
    assert "none (the role's capabilities were already at least this restrictive)" in text
