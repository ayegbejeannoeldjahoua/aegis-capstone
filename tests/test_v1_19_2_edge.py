"""v1.19.2 -- regression guards for the edge / auto-start additions:
  1. All persistent services have restart: unless-stopped so they auto-recover
     after a VM reboot (runtime-cell-image stays as restart: no).
  2. deploy-edge/ contains a parseable Caddyfile + compose overlay with caddy
     bound to 80/443 and using the SAF_PUBLIC_HOSTNAME variable.
  3. scripts/edge-up.sh, edge-down.sh, install-edge.sh are executable and
     reference the edge overlay.
  4. .env.prod.example documents SAF_PUBLIC_HOSTNAME.
"""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_all_persistent_services_auto_restart():
    doc = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    svcs = doc["services"]
    # runtime-cell-image is supposed to exit after building -> restart: no
    assert svcs["runtime-cell-image"]["restart"] == "no"
    # Every other service must auto-restart on dockerd boot
    for name in ["postgres", "keycloak", "opa", "vault", "api",
                 "frontend", "redis", "mongo"]:
        assert svcs[name].get("restart") == "unless-stopped", \
            f"{name} must have restart: unless-stopped"


def test_caddyfile_present_and_routes_known_paths():
    caddy = ROOT / "deploy-edge" / "Caddyfile"
    assert caddy.is_file()
    txt = caddy.read_text()
    # Uses the env-var hostname so the user can change the domain in one place
    assert "{$SAF_PUBLIC_HOSTNAME" in txt
    # Routes for the three backend planes
    assert "reverse_proxy api:8080" in txt
    assert "reverse_proxy keycloak:8080" in txt
    assert "reverse_proxy frontend:80" in txt
    # OIDC public paths must be routed to Keycloak
    assert "/realms/*" in txt


def test_edge_compose_overlay_binds_80_and_443():
    doc = yaml.safe_load((ROOT / "deploy-edge" / "docker-compose.edge.yml").read_text())
    caddy = doc["services"]["caddy"]
    ports = [str(p) for p in caddy["ports"]]
    assert any("80:80" in p for p in ports)
    assert any("443:443" in p for p in ports)
    assert caddy["restart"] == "unless-stopped"
    # Volumes must persist Let's Encrypt state
    assert any("caddy_data:/data" in str(v) for v in caddy["volumes"])


def test_edge_scripts_executable_and_reference_overlay():
    for name in ["edge-up.sh", "edge-down.sh", "install-edge.sh"]:
        p = ROOT / "scripts" / name
        assert p.is_file(), f"{name} missing"
        assert os.access(p, os.X_OK), f"{name} not executable"
    up = (ROOT / "scripts" / "edge-up.sh").read_text()
    assert "deploy-edge/docker-compose.edge.yml" in up


def test_env_prod_example_documents_public_hostname():
    txt = (ROOT / ".env.prod.example").read_text()
    assert "SAF_PUBLIC_HOSTNAME" in txt
    assert "OIDC_PUBLIC_ISSUER" in txt
    assert "SAF_CORS_ORIGINS" in txt



def test_caddy_intercepts_config_js_with_public_hostname():
    """v1.19.3 -- Caddy must serve /config.js with the public hostname so the
    SPA's window.SAF_CONFIG points at the public Keycloak, not localhost:8081.
    Without this, the SPA falls back to localhost:8081 on login and the
    browser fails with ERR_CONNECTION_REFUSED."""
    caddy = (ROOT / "deploy-edge" / "Caddyfile").read_text()
    assert "handle /config.js" in caddy
    assert "window.SAF_CONFIG" in caddy
    assert "KEYCLOAK_URL" in caddy
    assert "API_BASE" in caddy
    # And the URL must be templated from the env var, not hardcoded.
    assert "{$SAF_PUBLIC_HOSTNAME}" in caddy



def test_configure_edge_keycloak_present_and_called_by_installer():
    """v1.19.4 -- after bootstrap, install-edge.sh must update the sentinel-cli
    client's redirect URIs from SAF_PUBLIC_HOSTNAME, otherwise login fails with
    'Invalid parameter: redirect_uri'."""
    s = (ROOT / "scripts" / "configure-edge-keycloak.sh")
    assert s.is_file() and os.access(s, os.X_OK)
    txt = s.read_text()
    assert "SAF_PUBLIC_HOSTNAME" in txt
    assert "aegis-cli" in txt
    assert "redirectUris" in txt
    assert "webOrigins" in txt
    # Installer must invoke it.
    inst = (ROOT / "scripts" / "install-edge.sh").read_text()
    assert "configure-edge-keycloak.sh" in inst
