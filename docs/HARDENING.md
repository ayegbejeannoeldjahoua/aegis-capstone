# Hardening features (v0.9.0)

## Sigstore-style skill signing (Ed25519)

Skill manifests are signed asymmetrically. `signing.py` verifies the `signature` block:
`ed25519` (public-key) or the legacy `demo-hmac-sha256`. Only the private key can sign;
the API verifies with the public key (`SAF_SKILL_PUBLIC_KEY`), so there is no shared secret
to distribute. Re-sign a manifest with `python scripts/sign-skill.py <manifest.yaml>`
(private key from `SAF_SKILL_PRIVATE_KEY` or `deploy/keys/skill-signing-ed25519.key` — a
throwaway demo key; production holds the key in a KMS/HSM and signs in CI). Full Sigstore
(keyless OIDC signing + Rekor transparency log) is the next step.

## Semantic memory (pgvector)

Opt-in via `SAF_EMBED_ENABLED=true` (needs an embedding model, e.g. `ollama pull nomic-embed-text`).
On write, `memory.py` embeds the body and stores it in the `embedding vector(768)` column
(migration `0003`, HNSW cosine index). On read, the query is embedded and matched by cosine
similarity — the **tenant filter is applied before ranking**, so one tenant can never rank over
another's vectors. With embeddings disabled, retrieval falls back to keyword (`ILIKE`) search,
so the system runs with no embedding model present.

## Distributed rate limiting (Redis)

`ratelimit.py` selects a backend via `SAF_RATE_LIMIT_BACKEND` (`memory` | `redis`). The Redis
limiter (`SAF_REDIS_URL`) keeps a shared per-window counter so the limit holds across all API
replicas, not per-process. It **fails open** on a Redis error (a limiter outage never blocks
traffic). The compose stack runs a `redis` service and defaults the API to the redis backend;
if Redis is unreachable at startup the limiter transparently falls back to in-process.
