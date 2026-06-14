from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import yaml

from . import signing
from .logging_config import get_logger
from .settings import settings

logger = get_logger("aegis.skills")


def _candidate_paths() -> list[Path]:
    paths = []
    if settings.skills_path:
        paths.append(Path(settings.skills_path))
    paths.append(Path("/app/configs/skills"))
    paths.append(Path("configs/skills"))
    return paths


def canonical_manifest_bytes(manifest: dict) -> bytes:
    """Stable serialization of a manifest excluding its signature block, so the
    signature covers everything else deterministically."""
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def expected_signature(manifest: dict) -> str:
    return hmac.new(
        settings.skill_signing_key.encode(),
        canonical_manifest_bytes(manifest),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(manifest: dict) -> bool:
    """Verify a manifest signature (ed25519 or HMAC) via the signing module."""
    return signing.verify(manifest)


class SkillRegistry:
    def __init__(self, path: str | None = None):
        self.path = self._resolve_path(path)

    @staticmethod
    def _resolve_path(path: str | None) -> Path:
        if path:
            return Path(path)
        for p in _candidate_paths():
            if p.exists():
                return p
        return Path("configs/skills")

    def get(self, skill_id: str) -> dict:
        for f in sorted(self.path.glob("*.yaml")):
            data = yaml.safe_load(f.read_text())
            if data.get("skill_id") == skill_id:
                return data
        raise KeyError(skill_id)

    def is_enabled_for(self, manifest: dict, tenant_id: str, role: str) -> bool:
        enablement = manifest.get("role_enablement", {})
        tenant_map = enablement.get(tenant_id, {})
        return bool(tenant_map.get(role, False))

    def verify(self, skill_id: str) -> dict:
        """Integrity check only: confirm the manifest is signed. Whether a given
        role/tenant may *invoke* the skill is decided by RBAC/OPA, not here, so new
        tenants are not blocked by a static per-tenant enablement list."""
        manifest = self.get(skill_id)
        if settings.require_skill_signature and not verify_signature(manifest):
            logger.warning("skill signature invalid: %s", skill_id)
            raise PermissionError(f"skill signature invalid or unsigned: {skill_id}")
        return manifest

    def catalog(self) -> list[dict]:
        """Read-only listing of every available skill manifest + its governance
        metadata (signature status, declared tools/namespaces/model purposes)."""
        out: list[dict] = []
        for f in sorted(self.path.glob("*.yaml")):
            m = yaml.safe_load(f.read_text())
            cap = m.get("capabilities", {}) or {}
            mem = cap.get("memory", {}) or {}
            out.append({
                "skill_id": m.get("skill_id"), "name": m.get("name"), "risk_tier": m.get("risk_tier"),
                "tools": cap.get("tools", []) or [],
                "model_purposes": (cap.get("model", {}) or {}).get("purposes", []) or [],
                "reads": [r.get("namespace") for r in (mem.get("read") or [])],
                "writes": [w.get("namespace") for w in (mem.get("write") or [])],
                "signed": verify_signature(m),
            })
        return out

    def load_verified(self, skill_id: str, tenant_id: str, role: str) -> dict:
        """Load a skill manifest and enforce signature + per-tenant role
        enablement. Raises PermissionError/ValueError on failure."""
        manifest = self.get(skill_id)
        if settings.require_skill_signature and not verify_signature(manifest):
            logger.warning("skill signature invalid: %s", skill_id)
            raise PermissionError(f"skill signature invalid or unsigned: {skill_id}")
        if not self.is_enabled_for(manifest, tenant_id, role):
            raise PermissionError(f"skill '{skill_id}' not enabled for tenant={tenant_id} role={role}")
        return manifest


skill_registry = SkillRegistry()
