"""Every skill manifest is present and passes Ed25519 signature verification."""
from pathlib import Path

import yaml

import aegis_fabric.signing as signing
from aegis_fabric.skills import SkillRegistry

SKILLS = Path("configs/skills")
EXPECTED = {"assistant", "summarise-with-memory", "research-brief", "qa-over-docs", "meeting-notes",
            "invoice-extract", "expense-policy-check", "contract-review", "matter-intake",
            "ticket-triage", "kb-answer", "incident-summary", "access-review",
            "audit-digest", "runbook-exec"}


def _manifests():
    return [yaml.safe_load(f.read_text()) for f in sorted(SKILLS.glob("*.yaml"))]


def test_catalog_complete():
    ids = {m["skill_id"] for m in _manifests()}
    assert EXPECTED <= ids, EXPECTED - ids


def test_all_signatures_verify():
    for m in _manifests():
        assert signing.verify(m), f"signature failed: {m['skill_id']}"


def test_registry_loads_each():
    reg = SkillRegistry(str(SKILLS))
    for sid in EXPECTED:
        man = reg.verify(sid)
        assert man["skill_id"] == sid
        assert "capabilities" in man


def test_manifests_declare_known_tools():
    from aegis_fabric import tools
    for m in _manifests():
        for t in m["capabilities"].get("tools", []):
            assert t in tools.TOOLS, f"{m['skill_id']} references unknown tool {t}"
