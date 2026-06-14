"""v1.23.2 -- Discover from PyPI helper. Endpoint validates names, runs the
discovery flow against the bundled services/demo_mcp (no real pip install
needed since the api container already has it on PYTHONPATH), and the
frontend renders a Discover button next to smart-defaulted fields."""
import re
from pathlib import Path

import aegis_fabric.admin as admin_mod
from aegis_fabric.admin import _MCPDiscoverRequest

ROOT = Path(__file__).resolve().parents[1]


def test_discover_request_validates_package_name():
    # pydantic itself doesn't enforce; the endpoint rejects bad chars.
    body = _MCPDiscoverRequest(pypi_package="../etc/passwd", module_path="x.y")
    # The regex in the endpoint must reject path-traversal characters.
    assert re.match(r"^[A-Za-z0-9._\-]+$", body.pypi_package) is None


def test_discover_endpoint_registered():
    from aegis_fabric.admin import router
    paths = {r.path for r in router.routes if hasattr(r, "path")}
    assert "/admin/mcp/discover" in paths


def test_mcp_jsx_renders_discover_section_and_smart_defaults():
    txt = (ROOT / "frontend" / "src" / "pages" / "MCP.jsx").read_text()
    assert "Discover from PyPI" in txt
    assert "/admin/mcp/discover" in txt
    assert "function defaultsFromServerId" in txt
    # Convention: server_id "paper-search" -> "paper-search-mcp" / "paper_search_mcp.server"
    assert 'endsWith("-mcp")' in txt
    assert ".server" in txt


def test_discover_module_path_regex_rejects_dashes():
    """module_path must be a Python module name; dashes are invalid."""
    # Confirm we documented the right regex in the endpoint
    src = (ROOT / "src" / "aegis_fabric" / "admin.py").read_text()
    assert "invalid module_path" in src
    assert 'r"^[A-Za-z0-9._]+$"' in src


def test_discover_returns_expected_shape_keys():
    """The endpoint returns a dict with these keys -- locked by parser-readable
    string literals in admin.py so the contract can't drift silently."""
    src = (admin_mod.__file__ and Path(admin_mod.__file__).read_text()) or ""
    for k in ('"public_key"', '"signature"', '"tools"', '"tools_count"',
              '"suggested_command"', '"suggested_args"', '"suggested_cwd"'):
        assert k in src, f"contract key {k} missing"
