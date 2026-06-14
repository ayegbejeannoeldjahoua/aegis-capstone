from aegis_fabric.skills import SkillRegistry, verify_signature


def test_real_manifest_signature_valid():
    m = SkillRegistry(path="configs/skills").get("summarise-with-memory")
    assert verify_signature(m) is True  # ed25519 with the demo public key


def test_tampered_manifest_rejected():
    m = SkillRegistry(path="configs/skills").get("summarise-with-memory")
    m["capabilities"]["tools"].append("exfiltrate")
    assert verify_signature(m) is False


def test_unsigned_placeholder_rejected():
    assert verify_signature({"skill_id": "x", "signature": {"value": "replace-with-xyz"}}) is False


def test_role_enablement_per_tenant():
    reg = SkillRegistry(path="configs/skills")
    m = reg.get("summarise-with-memory")
    assert reg.is_enabled_for(m, "acme-corp", "analyst") is True
    assert reg.is_enabled_for(m, "acme-corp", "viewer") is False
    assert reg.is_enabled_for(m, "beta-corp", "lead") is False
