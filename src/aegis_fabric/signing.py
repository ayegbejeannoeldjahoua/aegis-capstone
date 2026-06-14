"""Skill-manifest signing & verification.

Supports two algorithms in a manifest's `signature` block:
  * ed25519        - asymmetric public-key signature (the Sigstore-style upgrade):
                     only the private key can sign; verifiers need only the public
                     key, so there is no shared secret to distribute or leak.
  * demo-hmac-sha256 - the original symmetric HMAC (kept for backward compatibility).

Full Sigstore (keyless OIDC signing via Fulcio + a Rekor transparency log) is a
further step; this captures the core security gain — asymmetric verification — in
a self-contained way.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .logging_config import get_logger
from .settings import settings

logger = get_logger("aegis.signing")


def canonical_manifest_bytes(manifest: dict) -> bytes:
    """Deterministic serialization of everything except the signature block."""
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def _hmac_value(manifest: dict) -> str:
    return hmac.new(settings.skill_signing_key.encode(), canonical_manifest_bytes(manifest), hashlib.sha256).hexdigest()


def _ed25519_verify(manifest: dict, signature_b64: str) -> bool:
    if not settings.skill_public_key:
        logger.warning("ed25519 verify requested but AEGIS_SKILL_PUBLIC_KEY is unset")
        return False
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(settings.skill_public_key))
        pub.verify(base64.b64decode(signature_b64), canonical_manifest_bytes(manifest))
        return True
    except Exception:
        return False


def verify(manifest: dict) -> bool:
    sig = manifest.get("signature", {}) or {}
    algorithm = sig.get("algorithm", "")
    value = sig.get("value", "")
    if not value or value.startswith("replace-with"):
        return False
    if algorithm in ("ed25519", "sigstore-ed25519"):
        return _ed25519_verify(manifest, value)
    if algorithm in ("demo-hmac-sha256", "hmac-sha256"):
        return hmac.compare_digest(value, _hmac_value(manifest))
    logger.warning("unknown signature algorithm: %s", algorithm)
    return False


# -- signing helpers (used by scripts/sign-skill.py, never by the running API) --
def sign_hmac(manifest: dict) -> str:
    return _hmac_value(manifest)


def sign_ed25519(manifest: dict, private_key_b64: str) -> str:
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    return base64.b64encode(priv.sign(canonical_manifest_bytes(manifest))).decode()
