#!/usr/bin/env python3
"""Sign a skill manifest with the Ed25519 private key.

Usage: python scripts/sign-skill.py [manifest.yaml]
Key source: AEGIS_SKILL_PRIVATE_KEY (base64) or deploy/keys/skill-signing-ed25519.key.
In production the private key lives in a KMS/HSM and signing runs in CI -- this demo
key is throwaway and must be rotated for any real deployment."""
import base64
import json
import os
import pathlib
import sys

import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def canonical(m: dict) -> bytes:
    body = {k: v for k, v in m.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "configs/skills/summarise-with-memory.skill.yaml"
    priv_b64 = os.getenv("AEGIS_SKILL_PRIVATE_KEY")
    if not priv_b64:
        kp = pathlib.Path("deploy/keys/skill-signing-ed25519.key")
        priv_b64 = kp.read_text().strip() if kp.exists() else None
    if not priv_b64:
        sys.exit("no private key: set AEGIS_SKILL_PRIVATE_KEY or provide deploy/keys/skill-signing-ed25519.key")
    p = pathlib.Path(path)
    m = yaml.safe_load(p.read_text())
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(priv_b64))
    sig = base64.b64encode(priv.sign(canonical(m))).decode()
    m["signature"] = {"algorithm": "ed25519", "value": sig}
    p.write_text(yaml.safe_dump(m, sort_keys=False))
    print(f"signed {path} with ed25519")


if __name__ == "__main__":
    main()
