"""Tool registry: metadata, real calculator/redact, egress derivation."""
import pytest
from aegis_fabric import tools


def test_registry_size_and_keys():
    assert len(tools.TOOLS) >= 16
    for t in ["web_search", "kb_search", "db_query", "calculator", "redact", "email_send", "file_export"]:
        assert t in tools.TOOLS


def test_calculator_is_real():
    assert tools.run_tool("calculator", {"expression": "2*(3+4)**2"})["result"] == 98


def test_calculator_rejects_unsafe():
    with pytest.raises(ValueError):
        tools.run_tool("calculator", {"expression": "__import__('os').system('x')"})


def test_redact_is_real():
    out = tools.run_tool("redact", {"text": "reach me a@b.com / 555-12-3456"})["redacted"]
    assert "[EMAIL]" in out and "[SSN]" in out and "@b.com" not in out


def test_egress_domain_derivation():
    assert tools.egress_domain("web_fetch", {"url": "https://wikipedia.org/x"}) == "wikipedia.org"
    assert tools.egress_domain("email_send", {"to": "x@acme-corp.example"}) == "acme-corp.example"
    assert tools.egress_domain("kb_search", {}) is None
    assert tools.egress_domain("external_lookup", {}) == "external"


def test_tool_resource_includes_egress():
    r = tools.tool_resource("web_fetch", "acme-corp", {"url": "https://evil.test/x"})
    assert r["tool_id"] == "web_fetch" and r["egress_domain"] == "evil.test"
    assert "egress_domain" not in tools.tool_resource("kb_search", "acme-corp", {})


def test_unknown_tool_raises():
    with pytest.raises(KeyError):
        tools.run_tool("nope", {})
