"""Curated vocabulary for the governance editor's list-typed capabilities, so
admins pick values from known options instead of typing them. Dynamic sets are
derived from the live model registry and the signed skill manifests; the stable
enums are listed here as the single source of truth.
"""
from __future__ import annotations

from . import tools
from .models import registry
from .skills import skill_registry

STATIC = {
    "model_purposes": ["chat", "embedding", "vision", "code"],
    "retention_classes": ["ephemeral", "standard", "long", "legal-hold"],
    "runtime_languages": ["python", "bash", "node"],
    "dual_control_actions": ["tenant.delete", "secret.rotate", "governance.edit"],
}


def governance_vocab() -> dict:
    raw = registry.raw or {}
    providers = raw.get("providers", {}) or {}
    provider_ids = sorted(providers.keys())
    model_ids = sorted({m["id"] for p in providers.values() for m in p.get("models", [])})
    regions = sorted({p.get("region", "AC1") for p in providers.values()}) or ["AC1"]

    namespaces = {"analyst-notes", "team-decisions"}
    for s in skill_registry.catalog():
        namespaces.update(s.get("reads") or [])
        namespaces.update(s.get("writes") or [])

    egress = {tools.egress_domain(t, {}) for t in tools.TOOLS}
    egress = sorted({e for e in egress if e} | {"*"})

    return {
        "namespaces": sorted(namespaces),
        "model_regions": regions,
        "providers": provider_ids,
        "model_ids": model_ids,
        "egress_suggestions": egress,
        **STATIC,
    }
