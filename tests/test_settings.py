import pytest
from pydantic import ValidationError

from aegis_fabric.settings import Settings


def _base_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("OIDC_ISSUER", "http://idp/realms/sentinel")


def test_production_rejects_change_me_secrets(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SAF_ENV", "production")
    monkeypatch.setenv("SAF_ADMIN_TOKEN", "change-me-admin-token")
    with pytest.raises(ValidationError):
        Settings()


def test_production_allows_strong_secrets(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SAF_ENV", "production")
    monkeypatch.setenv("SAF_ADMIN_TOKEN", "a-strong-admin-token")
    monkeypatch.setenv("SAF_LOCAL_MASTER_KEY", "a-strong-master-key-0123456789abcd")
    monkeypatch.setenv("VAULT_TOKEN", "a-strong-vault-token")
    monkeypatch.setenv("SAF_SKILL_SIGNING_KEY", "a-strong-skill-key")
    monkeypatch.setenv("SAF_AUDIT_KEY", "a-strong-audit-key")
    s = Settings()
    assert s.is_production


def test_development_allows_defaults(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SAF_ENV", "development")
    monkeypatch.setenv("SAF_ADMIN_TOKEN", "change-me-admin-token")
    s = Settings()
    assert not s.is_production


def test_insecure_override_escape_hatch(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SAF_ENV", "production")
    monkeypatch.setenv("SAF_ADMIN_TOKEN", "change-me-admin-token")
    monkeypatch.setenv("SAF_ALLOW_INSECURE_DEFAULTS", "true")
    Settings()  # should not raise
