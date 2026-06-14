"""v1.23.3 -- the smart-defaults onChange handler must keep deriving pypi_package
and module_path from server_id while the user hasn't manually edited those
fields. The v1.23.2 bug was: typing "p" set pypi_package="p-mcp", then the
|| short-circuit kept it stuck at "p-mcp" forever, so pip got asked for
"p-mcp" instead of "paper-search-mcp"."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_default_form_carries_touched_flags():
    txt = (ROOT / "frontend" / "src" / "pages" / "MCP.jsx").read_text()
    assert "_pypi_touched" in txt
    assert "_module_touched" in txt


def test_pypi_and_module_onchange_set_their_touched_flag():
    txt = (ROOT / "frontend" / "src" / "pages" / "MCP.jsx").read_text()
    assert "pypi_package: e.target.value, _pypi_touched: true" in txt
    assert "module_path: e.target.value, _module_touched: true" in txt


def test_server_id_onchange_uses_touched_flag_not_or_shortcircuit():
    """The v1.23.2 bug was using `form.pypi_package || d.pypi_package`. The
    v1.23.3 fix uses the touched flag instead. Regression guard."""
    txt = (ROOT / "frontend" / "src" / "pages" / "MCP.jsx").read_text()
    # The buggy shortcut must NOT be back.
    assert "form.pypi_package || d.pypi_package" not in txt
    assert "form.module_path  || d.module_path" not in txt
    # The fix must be present.
    assert "form._pypi_touched   ? form.pypi_package : d.pypi_package" in txt
    assert "form._module_touched ? form.module_path  : d.module_path" in txt
