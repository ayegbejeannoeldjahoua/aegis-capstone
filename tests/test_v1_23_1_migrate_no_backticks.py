"""v1.23.1 -- migrate.sh and other shell scripts must not contain backticks in
comments. Bash evaluates backticks as command substitution and on at least
some hosts mis-parses them even inside `#` comments, breaking the script
with `python: command not found` before any real work runs."""
import os
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_migrate_sh_has_no_backticks():
    txt = (SCRIPTS / "migrate.sh").read_text()
    assert "`" not in txt, "migrate.sh comments must not use backticks"


def test_migrate_sh_passes_bash_syntax_check():
    """bash -n parses without execution; catches any structural error."""
    if not os.path.exists("/bin/bash"):
        return
    r = subprocess.run(["/bin/bash", "-n", str(SCRIPTS / "migrate.sh")],
                       capture_output=True, text=True, timeout=5)
    assert r.returncode == 0, f"bash -n failed: {r.stderr}"


def test_migrate_sh_invokes_python3_inside_api():
    txt = (SCRIPTS / "migrate.sh").read_text()
    assert "python3 -m aegis_fabric.migrate" in txt
    assert "exec -T api" in txt
