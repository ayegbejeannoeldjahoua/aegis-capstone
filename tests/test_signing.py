import base64

from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import aegis_fabric.signing as signing


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pr = base64.b64encode(priv.private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption())).decode()
    pu = base64.b64encode(priv.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)).decode()
    return pr, pu


def test_ed25519_sign_and_verify(monkeypatch):
    pr, pu = _keypair()
    monkeypatch.setattr(signing.settings, "skill_public_key", pu)
    m = {"skill_id": "x", "capabilities": {"tools": ["t"]}}
    m["signature"] = {"algorithm": "ed25519", "value": signing.sign_ed25519(m, pr)}
    assert signing.verify(m) is True


def test_ed25519_tamper_rejected(monkeypatch):
    pr, pu = _keypair()
    monkeypatch.setattr(signing.settings, "skill_public_key", pu)
    m = {"skill_id": "x", "capabilities": {"tools": ["t"]}}
    m["signature"] = {"algorithm": "ed25519", "value": signing.sign_ed25519(m, pr)}
    m["capabilities"]["tools"].append("evil")
    assert signing.verify(m) is False


def test_ed25519_wrong_key_rejected(monkeypatch):
    pr, _ = _keypair()
    _, pu2 = _keypair()
    monkeypatch.setattr(signing.settings, "skill_public_key", pu2)
    m = {"skill_id": "x"}
    m["signature"] = {"algorithm": "ed25519", "value": signing.sign_ed25519(m, pr)}
    assert signing.verify(m) is False


def test_hmac_still_supported():
    m = {"skill_id": "x", "capabilities": {}}
    m["signature"] = {"algorithm": "demo-hmac-sha256", "value": signing.sign_hmac(m)}
    assert signing.verify(m) is True


def test_unsigned_rejected():
    assert signing.verify({"skill_id": "x", "signature": {"value": "replace-with-x"}}) is False
    assert signing.verify({"skill_id": "x"}) is False


def test_shipped_manifest_verifies_with_demo_key():
    import aegis_fabric.skills as skills
    m = skills.SkillRegistry(path="configs/skills").get("summarise-with-memory")
    assert m["signature"]["algorithm"] == "ed25519"
    assert signing.verify(m) is True
