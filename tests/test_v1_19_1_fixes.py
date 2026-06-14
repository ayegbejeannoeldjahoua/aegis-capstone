"""v1.19.1 -- regression guards for the two production fixes baked in:
  1. bootstrap.sh auto-sources .env (fixes 401 with custom SAF_ADMIN_TOKEN)
  2. docker-compose.yml allows .env to override OIDC issuer + CORS
     (fixes 'Invalid issuer' when SAF runs behind a public hostname)
"""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_sources_env_and_hints_on_401():
    txt = (ROOT / "scripts" / "bootstrap.sh").read_text()
    assert 'if [ -f "${ROOT}/.env" ]' in txt, "bootstrap must guard the source"
    assert "set -a" in txt and ". \"${ROOT}/.env\"" in txt and "set +a" in txt, \
        "bootstrap must export .env values"
    assert "401" in txt and "HINT" in txt, "must hint when api rejects with 401"
    assert os.access(ROOT / "scripts" / "bootstrap.sh", os.X_OK)


def test_compose_oidc_and_cors_are_overridable_by_env():
    doc = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    env = doc["services"]["api"]["environment"]
    assert env["OIDC_PUBLIC_ISSUER"].startswith("${OIDC_PUBLIC_ISSUER:-"), env["OIDC_PUBLIC_ISSUER"]
    assert env["OIDC_ISSUER"].startswith("${OIDC_ISSUER:-"), env["OIDC_ISSUER"]
    assert env["SAF_CORS_ORIGINS"].startswith("${SAF_CORS_ORIGINS:-"), env["SAF_CORS_ORIGINS"]


def test_env_prod_example_template_present():
    p = ROOT / ".env.prod.example"
    assert p.is_file()
    txt = p.read_text()
    assert "OIDC_PUBLIC_ISSUER" in txt
    assert "SAF_CORS_ORIGINS" in txt
    assert "Invalid issuer" in txt  # the WHY
