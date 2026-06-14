"""Platform-wide settings stored in the application DB as simple key/value rows.

Unlike per-tenant governance (which lives on roles/values), these are single global
knobs set by a platform admin. The first one is ``default_model`` -- the model that
serves every tenant/role unless overridden. When unset, callers fall back to the
model registry's configured default (configs/model_registry.yaml).
"""
from __future__ import annotations

from .db import get_conn

DEFAULT_MODEL_KEY = "default_model"


def get_setting(key: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM platform_settings WHERE key=%s", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str, updated_by: str = "platform-admin") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO platform_settings(key, value, updated_by) VALUES (%s,%s,%s) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, "
            "updated_by=EXCLUDED.updated_by, updated_at=now()",
            (key, value, updated_by),
        )


def get_default_model() -> str | None:
    """The platform-admin-selected global model, or None to fall back to the registry default."""
    return get_setting(DEFAULT_MODEL_KEY)


def set_default_model(model_id: str, updated_by: str = "platform-admin") -> None:
    set_setting(DEFAULT_MODEL_KEY, model_id, updated_by)
