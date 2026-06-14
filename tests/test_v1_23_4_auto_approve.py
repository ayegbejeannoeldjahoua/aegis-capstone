"""v1.23.4 -- MCP registrations auto-approve after signature + scan succeed,
unless SAF_MCP_REQUIRE_DUAL_CONTROL=true is set to opt back into the original
governance frame."""
from pathlib import Path

import aegis_fabric.settings as settings_mod

ROOT = Path(__file__).resolve().parents[1]


def test_settings_default_disables_dual_control():
    """The new default is auto-approve per platform-admin request."""
    assert settings_mod.settings.mcp_require_dual_control is False


def test_setting_is_env_overridable():
    """Operators can re-enable BR-SOD-02 by setting SAF_MCP_REQUIRE_DUAL_CONTROL=true."""
    src = (ROOT / "src" / "aegis_fabric" / "settings.py").read_text()
    assert 'alias="SAF_MCP_REQUIRE_DUAL_CONTROL"' in src
    assert "mcp_require_dual_control: bool" in src


def test_admin_endpoint_branches_on_setting():
    """The mcp_register endpoint must branch on the setting -- both code paths
    present, with the auto-approve path setting status='approved' immediately."""
    src = (ROOT / "src" / "aegis_fabric" / "admin.py").read_text()
    # Both branches must coexist.
    assert "_settings.mcp_require_dual_control:" in src
    # The dual-control branch still calls create_pending.
    assert '"mcp.register",' in src
    # The auto-approve branch sets status directly + audits the bypass.
    assert "status='approved'" in src
    assert '"mcp.register.auto-approved"' in src


def test_audit_event_carries_verification_verdict():
    """An auditor must be able to see what was actually checked at auto-approve time."""
    src = (ROOT / "src" / "aegis_fabric" / "admin.py").read_text()
    for k in ('"signature_ok"', '"scan_ok"', '"approver"', '"policy"'):
        assert k in src, f"audit verdict key {k} missing"


def test_frontend_help_text_explains_new_default():
    txt = (ROOT / "frontend" / "src" / "pages" / "MCP.jsx").read_text()
    assert "auto-approved" in txt
    assert "SAF_MCP_REQUIRE_DUAL_CONTROL" in txt
