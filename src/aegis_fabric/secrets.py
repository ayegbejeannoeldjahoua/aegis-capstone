from __future__ import annotations

import os

from .logging_config import get_logger
from .settings import settings

logger = get_logger("aegis.secrets")


class SecretProvider:
    def get(self, name: str) -> str | None:
        raise NotImplementedError


class EnvSecretProvider(SecretProvider):
    def get(self, name: str) -> str | None:
        return os.getenv(name)


class VaultSecretProvider(SecretProvider):
    """Reads provider secrets from Vault KV v2 at ``aegis/models/<name>``.

    An environment fallback is available for local compose convenience but is
    gated behind ``AEGIS_SECRET_ENV_FALLBACK`` so production can disable it.
    """

    def __init__(self):
        import hvac

        self.client = hvac.Client(url=settings.vault_addr, token=settings.vault_token)
        self._env_fallback = settings.secret_env_fallback

    def get(self, name: str) -> str | None:
        if self._env_fallback and os.getenv(name):
            return os.getenv(name)
        try:
            path = f"aegis/models/{name.lower()}"
            result = self.client.secrets.kv.v2.read_secret_version(path=path)
            return result["data"]["data"].get("value")
        except Exception as e:
            logger.warning("vault secret read failed for %s: %s", name, e)
            if self._env_fallback:
                return os.getenv(name)
            return None


_provider: SecretProvider | None = None


def secrets() -> SecretProvider:
    global _provider
    if _provider is None:
        if settings.secret_backend == "vault":
            try:
                _provider = VaultSecretProvider()
            except Exception as e:
                logger.warning("vault unavailable, falling back to env secrets: %s", e)
                _provider = EnvSecretProvider()
        else:
            _provider = EnvSecretProvider()
    return _provider


def reset_provider_cache() -> None:
    """Test hook to drop the memoized provider."""
    global _provider
    _provider = None
