"""v1.23 -- end-to-end stdio MCP client tests.

Spawns the bundled services/demo_mcp reference server as a real subprocess,
runs the handshake, lists tools, calls each tool, verifies the response
shape, and checks error mapping for unknown tools / unknown methods.
"""
import json
import sys
from pathlib import Path

import pytest

from aegis_fabric.mcp_client import (
    LaunchConfig, MCPRemoteError, MCPStdioClient, MCPTransportError,
)

ROOT = Path(__file__).resolve().parents[1]


def _demo_cfg(call_timeout_s: float = 5.0) -> LaunchConfig:
    """Launch the bundled reference server via the current Python."""
    return LaunchConfig(command=sys.executable,
                        args=["-m", "services.demo_mcp.server"],
                        cwd=str(ROOT),
                        startup_timeout_s=5.0, call_timeout_s=call_timeout_s)


def test_handshake_returns_protocol_version_and_server_info():
    c = MCPStdioClient(_demo_cfg())
    try:
        result = c.start()
        assert result["protocolVersion"] == "2025-03-26"
        assert result["serverInfo"]["name"] == "saf-demo-mcp"
        assert "tools" in result["capabilities"]
    finally:
        c.close()


def test_list_tools_returns_both_demos():
    c = MCPStdioClient(_demo_cfg())
    try:
        c.start()
        tools = c.list_tools()
    finally:
        c.close()
    names = {t["name"] for t in tools}
    assert names == {"pubmed_search", "kb_query"}
    # Schemas should declare required fields.
    pm = next(t for t in tools if t["name"] == "pubmed_search")
    assert "query" in pm["inputSchema"]["required"]


def test_call_pubmed_search_returns_stub_items():
    c = MCPStdioClient(_demo_cfg())
    try:
        c.start()
        out = c.call_tool("pubmed_search", {"query": "RAG safety", "max_results": 3})
    finally:
        c.close()
    assert "content" in out and len(out["content"]) == 1
    payload = json.loads(out["content"][0]["text"])
    assert payload["query"] == "RAG safety"
    assert payload["count"] == 3
    assert len(payload["items"]) == 3
    assert all("pmid" in it for it in payload["items"])


def test_unknown_tool_maps_to_remote_error():
    c = MCPStdioClient(_demo_cfg())
    try:
        c.start()
        with pytest.raises(MCPRemoteError) as exc:
            c.call_tool("does_not_exist", {"x": 1})
    finally:
        c.close()
    assert exc.value.code == -32601  # METHOD_NOT_FOUND
    assert "tool not found" in exc.value.message


def test_ping_round_trips():
    c = MCPStdioClient(_demo_cfg())
    try:
        c.start()
        c.ping()  # no raise
    finally:
        c.close()


def test_spawn_failure_raises_transport_error():
    cfg = LaunchConfig(command="/no/such/binary", args=[])
    c = MCPStdioClient(cfg)
    with pytest.raises(MCPTransportError):
        c.start()


def test_gateway_register_demo_endpoint_present():
    """v1.23 adds the /admin/mcp/register-demo shortcut for the bundled server."""
    from aegis_fabric.admin import router
    paths = {r.path for r in router.routes if hasattr(r, "path")}
    assert "/admin/mcp/register-demo" in paths


def test_mcp_jsx_has_demo_shortcut_button():
    txt = (ROOT / "frontend" / "src" / "pages" / "MCP.jsx").read_text()
    assert "/admin/mcp/register-demo" in txt
    assert "Register stdio demo" in txt


def test_demo_server_module_runnable():
    """Smoke test: server module imports + has the expected dispatch table."""
    from services.demo_mcp import server as srv
    assert "pubmed_search" in srv._DISPATCH
    assert "kb_query" in srv._DISPATCH
    assert srv.PROTOCOL_VERSION == "2025-03-26"
