"""v1.20.1 -- migrate.sh must not depend on host-side `python`. It runs the
migrator inside the api container via docker compose exec, which has python3
+ DATABASE_URL + the migrations dir already in place."""
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate.sh"


def test_migrate_does_not_use_bare_python():
    txt = SCRIPT.read_text()
    # Bare `python` is the breakage we're fixing.
    assert "python -m aegis_fabric.migrate" not in txt
    # Must invoke python3 inside the api container.
    assert "python3 -m aegis_fabric.migrate" in txt
    assert "docker compose" in txt
    assert "exec -T api" in txt


def test_migrate_handles_edge_overlay_if_present():
    txt = SCRIPT.read_text()
    # If deploy-edge/docker-compose.edge.yml exists, the script must include it
    # so volumes/networks line up with the rest of the stack.
    assert "deploy-edge/docker-compose.edge.yml" in txt
