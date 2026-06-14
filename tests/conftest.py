"""Test bootstrap: set a self-contained environment BEFORE importing the
package so module-level `Settings()` / registry construction succeed without
any live services."""
import os

os.environ.setdefault("SAF_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://saf:saf@localhost:5432/saf")
os.environ.setdefault("OIDC_ISSUER", "http://localhost:8081/realms/sentinel")
os.environ.setdefault("OIDC_AUDIENCE", "aegis-api")
os.environ.setdefault("SAF_SECRET_BACKEND", "env")
os.environ.setdefault("SAF_SKILL_SIGNING_KEY", "demo-skill-signing-key")
os.environ.setdefault("SAF_REQUIRE_OPA", "false")
os.environ.setdefault("SAF_LOG_JSON", "false")
os.environ.setdefault("SAF_SKILL_PUBLIC_KEY", "Ms5VAI+2S9EJZZSGcV/EPwAyvpx/RGbRELjcIrfgGc8=")
os.environ.setdefault("SAF_RATE_LIMIT_BACKEND", "memory")
os.environ.setdefault("SAF_EMBED_ENABLED", "false")
