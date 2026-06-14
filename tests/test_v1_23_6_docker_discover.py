"""v1.23.6 -- Discover from Docker image. Adds parallel discover endpoint that
spawns the MCP server via `docker run -i --rm <image>` instead of `python -m
<module>`. Required for Docker MCP Hub servers (mcp/* images) like aws-core,
brave-search, elasticsearch, etc. that don't ship on PyPI."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_discover_docker_endpoint_registered():
    from aegis_fabric.admin import router
    paths = {r.path for r in router.routes if hasattr(r, "path")}
    assert "/admin/mcp/discover-docker" in paths


def test_discover_docker_validates_image_name():
    src = (ROOT / "src" / "aegis_fabric" / "admin.py").read_text()
    assert "invalid docker_image" in src
    # Standard image-ref characters only -- no shell metas.
    assert "^[A-Za-z0-9][A-Za-z0-9._/" in src


def test_dockerfile_api_installs_docker_cli():
    df = (ROOT / "Dockerfile.api").read_text()
    assert "docker-27" in df or "docker.io" in df, "docker CLI install missing from Dockerfile.api"
    assert "/usr/local/bin/docker" in df or "apt-get install" in df


def test_mcp_jsx_has_discover_docker_section():
    txt = (ROOT / "frontend" / "src" / "pages" / "MCP.jsx").read_text()
    assert "Discover from Docker image" in txt
    assert "/admin/mcp/discover-docker" in txt
    # Smart default: typing server_id "aws-core" should pre-fill docker_image "mcp/aws-core"
    assert "`mcp/${v}`" in txt
    # Touched-flag for docker_image so smart default keeps tracking until user types
    assert "_docker_touched" in txt


def test_discover_docker_returns_same_contract_keys_as_pypi():
    """The endpoint must return the same key set as /admin/mcp/discover so the
    frontend reuses the same field-fill logic."""
    src = (ROOT / "src" / "aegis_fabric" / "admin.py").read_text()
    for k in ('"public_key"', '"signature"', '"tools"', '"tools_count"',
              '"suggested_command"', '"suggested_args"', '"suggested_cwd"'):
        # Each key must appear in BOTH discover endpoints. We just confirm
        # the docker variant has its share -- there should be at least 2
        # occurrences in the file (pypi + docker).
        assert src.count(k) >= 2, f"{k} missing from one of the discover endpoints"
