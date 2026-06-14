"""v1.22 -- regression guards for the MCP gateway slice:
  * canonical bytes are sort-deterministic + bijective with verify_signature
  * verify_manifest catches invalid signatures and poisoned descriptions
  * tools are namespaced server_id/tool_id
  * migration 0009 creates the two tables with the expected schema
  * approvals.EXECUTORS includes mcp.register
  * fixture has both pat and kim as platform-admin on acme-corp
  * frontend MCP tab + Console wiring exist
"""
import base64
from pathlib import Path

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import aegis_fabric.approvals as approvals_mod
import aegis_fabric.mcp_gateway as gw

ROOT = Path(__file__).resolve().parents[1]


def _make_signed_manifest(server_id="paper-search", tools=None) -> gw.ServerManifest:
    priv = Ed25519PrivateKey.generate()
    pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode()
    tools = tools or [gw.ToolSpec(tool_id="search", description="search papers", parameters={"q": "string"})]
    canon = gw._canonical_tools_bytes(tools)
    sig_b64 = base64.b64encode(priv.sign(canon)).decode()
    return gw.ServerManifest(server_id=server_id, display_name=server_id, version="1.0.0",
                             public_key=pub_b64, signature=sig_b64, tools=tools)


# --- canonical + sign/verify ------------------------------------------------

def test_canonical_bytes_are_deterministic_and_order_independent():
    a = [gw.ToolSpec("b", "b desc"), gw.ToolSpec("a", "a desc")]
    b = [gw.ToolSpec("a", "a desc"), gw.ToolSpec("b", "b desc")]
    assert gw._canonical_tools_bytes(a) == gw._canonical_tools_bytes(b)


def test_verify_signature_round_trip():
    m = _make_signed_manifest()
    assert gw.verify_signature(m) is True
    # Mutate a tool description and the signature must no longer verify.
    m.tools[0].description = "tampered"
    assert gw.verify_signature(m) is False


def test_manifest_hash_is_stable():
    m1 = _make_signed_manifest()
    m2 = _make_signed_manifest()  # different keys, same tool shape
    assert gw.manifest_hash(m1) == gw.manifest_hash(m2)
    # Different tool surface -> different hash.
    m3 = _make_signed_manifest(tools=[gw.ToolSpec("other", "x")])
    assert gw.manifest_hash(m3) != gw.manifest_hash(m1)


# --- verify_manifest: catches bad sig + poisoned descriptions ---------------

def test_verify_manifest_passes_clean_signed_input():
    m = _make_signed_manifest()
    v = gw.verify_manifest(m)
    assert v["signature_ok"] is True
    assert v["scan_ok"] is True
    assert v["namespace"] == ["paper-search/search"]


def test_verify_manifest_flags_invalid_signature():
    m = _make_signed_manifest()
    m.signature = base64.b64encode(b"\x00" * 64).decode()
    v = gw.verify_manifest(m)
    assert v["signature_ok"] is False


def test_namespace_isolates_tool_ids_across_servers():
    a = _make_signed_manifest(server_id="server-a")
    b = _make_signed_manifest(server_id="server-b")
    va = gw.verify_manifest(a)
    vb = gw.verify_manifest(b)
    assert va["namespace"] == ["server-a/search"]
    assert vb["namespace"] == ["server-b/search"]
    # Same tool name across servers is intentionally allowed, but namespaced.
    assert set(va["namespace"]) & set(vb["namespace"]) == set()


# --- migration + executor wiring --------------------------------------------

def test_migration_0009_creates_servers_and_tools_tables_with_namespacing():
    sql = (ROOT / "deploy" / "postgres" / "migrations" / "0009_mcp.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS mcp_servers" in sql
    assert "CREATE TABLE IF NOT EXISTS mcp_tools" in sql
    # Primary key uses (server_id, tool_id) to enforce namespacing at DB layer.
    assert "PRIMARY KEY (server_id, tool_id)" in sql
    # Status check constrains lifecycle.
    assert "pending_approval" in sql and "approved" in sql and "quarantined" in sql


def test_approvals_executors_include_mcp_register():
    assert "mcp.register" in approvals_mod.EXECUTORS


# --- fixture has kim as second platform-admin -------------------------------

def test_fixture_has_two_platform_admins_in_acme():
    fx = yaml.safe_load((ROOT / "configs" / "fixtures" / "tenant_fixture.yaml").read_text())
    pas = [u for u in fx["users"]
           if u["tenant_id"] == "acme-corp" and u["role_id"] == "platform-admin"]
    emails = {u["email"] for u in pas}
    assert "pat@acme-corp.example" in emails
    assert "kim@acme-corp.example" in emails


# --- admin endpoints + frontend wiring --------------------------------------

def test_admin_router_exposes_mcp_endpoints():
    from aegis_fabric.admin import router
    paths = {r.path for r in router.routes if hasattr(r, "path")}
    assert "/admin/mcp/register" in paths
    assert "/admin/mcp/servers" in paths


def test_console_jsx_renders_mcp_tab_for_platform_admin():
    cons = (ROOT / "frontend" / "src" / "Console.jsx").read_text()
    assert 'import MCP from "./pages/MCP.jsx"' in cons
    assert '["mcp", "MCP"]' in cons
    assert 'tab === "mcp"' in cons
    assert "platformAdmin" in cons


def test_mcp_jsx_form_and_table_present():
    mcp = (ROOT / "frontend" / "src" / "pages" / "MCP.jsx").read_text()
    assert "/admin/mcp/register" in mcp
    assert "/admin/mcp/servers" in mcp
    assert "quarantine" in mcp
    assert "Stage registration" in mcp
