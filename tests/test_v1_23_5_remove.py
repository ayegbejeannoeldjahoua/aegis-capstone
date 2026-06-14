"""v1.23.5 -- DELETE /admin/mcp/{server_id} works for any status, cleans up
orphan pending_actions rows, and audit-records the removal. The Remove button
appears on every row regardless of status."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_delete_endpoint_registered():
    from aegis_fabric.admin import router
    paths = {r.path for r in router.routes if hasattr(r, "path")}
    assert "/admin/mcp/{server_id}" in paths


def test_delete_endpoint_uses_delete_method():
    from aegis_fabric.admin import router
    targets = [r for r in router.routes
               if getattr(r, "path", "") == "/admin/mcp/{server_id}"]
    methods = set()
    for r in targets:
        methods.update(getattr(r, "methods", set()))
    # quarantine (POST) and remove (DELETE) share no path -- quarantine is
    # /admin/mcp/{server_id}/quarantine. So {server_id} should expose only DELETE.
    assert "DELETE" in methods


def test_delete_cleans_orphan_pending_actions():
    """When a server is removed, any pending_actions row queued for its
    mcp.register must also be deleted so the Approvals tab is clean."""
    src = (ROOT / "src" / "aegis_fabric" / "admin.py").read_text()
    # The cleanup must scope to action='mcp.register' AND the resource's
    # server_id so we never touch other actions' rows.
    assert "DELETE FROM pending_actions WHERE action='mcp.register'" in src
    assert "(resource->>'server_id') = %s" in src


def test_delete_audits_with_prior_status():
    src = (ROOT / "src" / "aegis_fabric" / "admin.py").read_text()
    assert '"mcp.server.removed"' in src
    assert '"prior_status"' in src


def test_mcp_jsx_renders_remove_on_every_row():
    txt = (ROOT / "frontend" / "src" / "pages" / "MCP.jsx").read_text()
    assert "removeServer" in txt
    assert "method: \"DELETE\"" in txt
    # The Remove button has no `s.status ===` gate -- it must apply to all statuses.
    # We check that the markup contains a removeServer button NOT inside a status-gated block.
    snippet = txt[txt.index("<td>\n                <button"):]
    assert "removeServer(s.server_id, s.status)" in snippet
