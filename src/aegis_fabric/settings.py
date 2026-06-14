from __future__ import annotations

import secrets as _secrets
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Values are sourced from environment variables (see ``.env.example``).
    Defaults that contain the word ``change-me`` are *development-only* and the
    application refuses to boot with them when ``AEGIS_ENV=production`` unless
    ``AEGIS_ALLOW_INSECURE_DEFAULTS=true`` is explicitly set.
    """

    model_config = SettingsConfigDict(extra="ignore", env_file=None)

    # Core
    env: Literal["production", "staging", "development", "test"] = Field(
        default="production", alias="AEGIS_ENV"
    )
    public_base_url: str = Field(default="http://localhost:8080", alias="AEGIS_PUBLIC_BASE_URL")
    log_level: str = Field(default="INFO", alias="AEGIS_LOG_LEVEL")
    log_json: bool = Field(default=True, alias="AEGIS_LOG_JSON")
    allow_insecure_defaults: bool = Field(default=False, alias="AEGIS_ALLOW_INSECURE_DEFAULTS")

    # Database
    database_url: str = Field(alias="DATABASE_URL")
    db_pool_min: int = Field(default=1, alias="AEGIS_DB_POOL_MIN")
    db_pool_max: int = Field(default=10, alias="AEGIS_DB_POOL_MAX")

    # Identity / OIDC
    oidc_issuer: str = Field(alias="OIDC_ISSUER")
    oidc_public_issuer: str | None = Field(default=None, alias="OIDC_PUBLIC_ISSUER")
    oidc_audience: str = Field(default="aegis-api", alias="OIDC_AUDIENCE")
    jwks_cache_seconds: int = Field(default=300, alias="AEGIS_JWKS_CACHE_SECONDS")

    # v1.20 BR-CAP-02: re-authentication freshness window for sensitive actions
    # (dual-control approvals, governance writes, MCP registrations, ...).
    # The user's session may be valid (under session_max_minutes), but sensitive
    # endpoints additionally require the token to have been issued within the
    # last N minutes -- otherwise force a re-login to confirm presence.
    sensitive_action_max_age_minutes: int = Field(default=30, alias="AEGIS_SENSITIVE_ACTION_MAX_AGE_MINUTES")

    # v1.23.4 MCP gateway -- when False, registrations auto-approve after
    # signature verification + injection scan succeed (no second-admin needed).
    # When True, the dual-control queue is required (BR-SOD-02 governance frame
    # remains in place). Default False per platform-admin request; flip to True
    # in .env to re-enable dual-control.
    mcp_require_dual_control: bool = Field(default=False, alias="AEGIS_MCP_REQUIRE_DUAL_CONTROL")

    # Authorization (OPA PDP)
    opa_url: str = Field(default="http://opa:8181", alias="OPA_URL")
    opa_package: str = Field(default="aegis.authz", alias="OPA_PACKAGE")
    require_opa: bool = Field(default=True, alias="AEGIS_REQUIRE_OPA")
    opa_timeout_seconds: float = Field(default=5.0, alias="AEGIS_OPA_TIMEOUT_SECONDS")

    # Admin surface
    admin_token: str = Field(default="change-me-admin-token", alias="AEGIS_ADMIN_TOKEN")

    # Secrets
    secret_backend: Literal["vault", "env"] = Field(default="vault", alias="AEGIS_SECRET_BACKEND")
    secret_env_fallback: bool = Field(default=True, alias="AEGIS_SECRET_ENV_FALLBACK")
    vault_addr: str = Field(default="http://vault:8200", alias="VAULT_ADDR")
    vault_token: str = Field(default="change-me-vault-token", alias="VAULT_TOKEN")

    # Audit
    local_master_key: str = Field(default="change-me-local-master-key-32bytes", alias="AEGIS_LOCAL_MASTER_KEY")
    audit_key: str | None = Field(default=None, alias="AEGIS_AUDIT_KEY")
    encrypt_audit: bool = Field(default=True, alias="AEGIS_ENCRYPT_AUDIT")
    audit_verify_max_rows: int = Field(default=100_000, alias="AEGIS_AUDIT_VERIFY_MAX_ROWS")

    # Model routing
    default_model: str = Field(default="openai/gpt-4.1", alias="AEGIS_DEFAULT_MODEL")
    model_region: str = Field(default="AC1", alias="AEGIS_MODEL_REGION")
    model_timeout_seconds: int = Field(default=90, alias="AEGIS_MODEL_TIMEOUT_SECONDS")
    model_max_output_tokens: int = Field(default=4096, alias="AEGIS_MODEL_MAX_OUTPUT_TOKENS")
    inspectors_enabled: bool = Field(default=True, alias="AEGIS_INSPECTORS_ENABLED")
    isa_enabled: bool = Field(default=True, alias="AEGIS_ISA_ENABLED")
    model_max_retries: int = Field(default=2, alias="AEGIS_MODEL_MAX_RETRIES")
    model_registry_path: str | None = Field(default=None, alias="AEGIS_MODEL_REGISTRY_PATH")

    # Runtime cells
    runtime_backend: str = Field(default="docker", alias="AEGIS_RUNTIME_BACKEND")
    runtime_image: str = Field(default="aegis-runtime-cell:latest", alias="AEGIS_RUNTIME_IMAGE")
    runtime_network: str = Field(default="none", alias="AEGIS_RUNTIME_NETWORK")
    runtime_memory_limit: str = Field(default="512m", alias="AEGIS_RUNTIME_MEMORY_LIMIT")
    runtime_cpu_quota: int = Field(default=100_000, alias="AEGIS_RUNTIME_CPU_QUOTA")
    runtime_timeout_seconds: int = Field(default=60, alias="AEGIS_RUNTIME_TIMEOUT_SECONDS")
    runtime_pids_limit: int = Field(default=128, alias="AEGIS_RUNTIME_PIDS_LIMIT")

    # Rate limiting (token bucket per subject)
    rate_limit_enabled: bool = Field(default=True, alias="AEGIS_RATE_LIMIT_ENABLED")
    rate_limit_per_minute: int = Field(default=60, alias="AEGIS_RATE_LIMIT_PER_MINUTE")

    # Keycloak admin (authentication-only provisioning of login identities)
    kc_admin_base: str = Field(default="http://keycloak:8080", alias="AEGIS_KC_ADMIN_BASE")
    kc_admin_user: str = Field(default="admin", alias="KEYCLOAK_ADMIN")
    kc_admin_password: str = Field(default="admin_change_me", alias="KEYCLOAK_ADMIN_PASSWORD")
    kc_realm: str = Field(default="aegis", alias="AEGIS_KC_REALM")
    kc_provisioning_enabled: bool = Field(default=True, alias="AEGIS_KC_PROVISIONING_ENABLED")
    kc_public_client_id: str = Field(default="aegis-cli", alias="AEGIS_KC_PUBLIC_CLIENT_ID")

    # RBAC / identity (app-DB-centric authorization)
    allow_email_binding: bool = Field(default=True, alias="AEGIS_ALLOW_EMAIL_BINDING")
    allow_group_fallback: bool = Field(default=False, alias="AEGIS_ALLOW_GROUP_FALLBACK")
    run_migrations_on_startup: bool = Field(default=True, alias="AEGIS_RUN_MIGRATIONS_ON_STARTUP")
    sync_opa_on_startup: bool = Field(default=True, alias="AEGIS_SYNC_OPA_ON_STARTUP")
    push_opa_policy_on_startup: bool = Field(default=True, alias="AEGIS_PUSH_OPA_POLICY_ON_STARTUP")
    # Continuous state export: a background task writes an idempotent governance seed to
    # export_path whenever a governance change is detected, so the on-disk setup file stays
    # current for a bare-scratch reinstall. No secrets / no sub bindings are written.
    export_enabled: bool = Field(default=False, alias="AEGIS_EXPORT_ENABLED")
    export_path: str = Field(default="/app/exports/seed-state.sql", alias="AEGIS_EXPORT_PATH")
    export_interval_seconds: int = Field(default=15, alias="AEGIS_EXPORT_INTERVAL")
    cors_origins: str = Field(default="http://localhost:5173", alias="AEGIS_CORS_ORIGINS")

    # Skill signing (asymmetric / Sigstore-style verification)
    skill_public_key: str = Field(default="Ms5VAI+2S9EJZZSGcV/EPwAyvpx/RGbRELjcIrfgGc8=", alias="AEGIS_SKILL_PUBLIC_KEY")

    # Distributed rate limiting
    rate_limit_backend: str = Field(default="memory", alias="AEGIS_RATE_LIMIT_BACKEND")  # memory | redis
    redis_url: str = Field(default="redis://redis:6379/0", alias="AEGIS_REDIS_URL")
    budget_fail_open: bool = Field(default=True, alias="AEGIS_BUDGET_FAIL_OPEN")
    mongo_url: str = Field(default="mongodb://mongo:27017", alias="AEGIS_MONGO_URL")
    docs_enabled: bool = Field(default=True, alias="AEGIS_DOCS_ENABLED")

    # Semantic memory (pgvector + sentence-transformers). On by default; the
    # embedder model is baked into the api image at build time (see
    # Dockerfile.api). Toggle off only for environments where you want pure
    # keyword retrieval (e.g. air-gapped without the model files).
    embed_enabled: bool = Field(default=True, alias="AEGIS_EMBED_ENABLED")
    embed_base: str = Field(default="", alias="AEGIS_EMBED_BASE")  # unused in-process
    embed_model: str = Field(default="sentence-transformers/all-mpnet-base-v2", alias="AEGIS_EMBED_MODEL")
    embed_dim: int = Field(default=768, alias="AEGIS_EMBED_DIM")
    embed_timeout: int = Field(default=30, alias="AEGIS_EMBED_TIMEOUT")

    # Skill registry
    skills_path: str | None = Field(default=None, alias="AEGIS_SKILLS_PATH")
    skill_signing_key: str = Field(default="change-me-skill-signing-key", alias="AEGIS_SKILL_SIGNING_KEY")
    require_skill_signature: bool = Field(default=True, alias="AEGIS_REQUIRE_SKILL_SIGNATURE")

    @property
    def is_production(self) -> bool:
        return self.env in ("production", "staging")

    @model_validator(mode="after")
    def _reject_insecure_defaults_in_prod(self) -> "Settings":
        if not self.is_production or self.allow_insecure_defaults:
            return self
        offenders: list[str] = []
        checks = {
            "AEGIS_ADMIN_TOKEN": self.admin_token,
            "AEGIS_LOCAL_MASTER_KEY": self.local_master_key,
            "VAULT_TOKEN": self.vault_token,
            "AEGIS_SKILL_SIGNING_KEY": self.skill_signing_key,
        }
        for name, value in checks.items():
            if value and "change-me" in value:
                offenders.append(name)
        if self.encrypt_audit and not self.audit_key and "change-me" in self.local_master_key:
            offenders.append("AEGIS_AUDIT_KEY/AEGIS_LOCAL_MASTER_KEY")
        if offenders:
            raise ValueError(
                "Insecure default secrets detected in production for: "
                + ", ".join(sorted(set(offenders)))
                + ". Set real values or AEGIS_ALLOW_INSECURE_DEFAULTS=true for non-prod."
            )
        return self


settings = Settings()
