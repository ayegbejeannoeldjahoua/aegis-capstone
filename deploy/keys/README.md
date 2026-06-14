# Skill-signing keys (DEMO)

`skill-signing-ed25519.key` is a **throwaway demo** Ed25519 private key (base64 raw bytes)
used only so `scripts/sign-skill.py` can re-sign the bundled skill manifest locally.

The matching public key is set via `SAF_SKILL_PUBLIC_KEY` and is what the API uses to verify.

**Production:** never ship a private key. Hold it in a KMS/HSM, sign manifests in CI, and rotate
this demo key. The full Sigstore path (keyless OIDC signing + Rekor transparency log) is the
next step beyond this asymmetric scheme.
