# Aegis AI Governance Platform — Production Readiness Review (v1.0.0)

**Reviewed lineage:** `sentinel_agent_fabric_production.zip` (v0.3.0) → consolidated release **v1.0.0**
**Review date:** 23 May 2026
**Scope:** A full critical audit of the original package, the remediation that followed, and the
architecture the platform evolved into — app-DB-centric authorization, a web UI, dynamic
tenant/role/governance management, and three hardening features.

---

## 1. Executive summary

The original package (v0.3.0) was a well-structured but mislabelled **demo scaffold**: the
directory said "production," yet a single defect meant it could not perform its core function
(the PDP queried a policy document the Rego never defined, so every request failed closed), its
cross-tenant isolation check was tautological, its admin and audit surfaces were unauthenticated,
and it had no tests.

It is now a **working, governed, multi-tenant platform with a web UI**. Authentication and
authorization are cleanly separated (Keycloak proves identity; the application database, enforced
through a generic OPA policy, decides what each role may do). Tenants, roles and per-role
capabilities are managed dynamically through an admin API and a React console — adding a tenant or
changing governance never requires a code or policy edit. Three hardening features (asymmetric
skill signing, semantic memory, distributed rate limiting) round out the release.

The whole vertical is proven end-to-end in a browser: log in → create a tenant → assign a user
(with an auto-provisioned login) → that user logs in → governed actions apply → change a role's
capabilities live and watch enforcement change. The test suite is green: **65 Python tests plus
OPA policy tests, ruff clean.**

### Verdict at a glance

| Dimension | Original (v0.3.0) | Now (v1.0.0) |
|---|---|---|
| Core request flow works under defaults | No — always 403 | Yes, end-to-end incl. a real LLM answer |
| Cross-tenant isolation enforced | No — tautological check | Yes — generic OPA over per-tenant capabilities |
| Add tenants / roles / change governance | Hardcoded; required code edits | Dynamic via admin API + web UI; no code/policy edits |
| Identity model | Tenancy derived from token groups | Keycloak authn-only; app DB owns RBAC (sub-keyed) |
| User interface | None (curl only) | React SPA (login, tenants, users, governance, test console) |
| Admin / audit surfaces protected | No | Yes (admin-guarded; audit reads tenant-scoped) |
| Skill signing | Shared-secret HMAC | Ed25519 public-key (Sigstore-style) |
| Memory retrieval | Substring only | Semantic (pgvector) with keyword fallback |
| Rate limiting | None | Per-process or shared Redis across replicas |
| Automated tests | None | 65 unit + OPA policy tests; lint; image build |

---

## 2. Current architecture

**Authentication vs authorization are separated.** Keycloak authenticates a person and issues a
signed token (`sub`, `email`). The **application database is the source of truth** for tenancy and
role capabilities. `auth.py` validates the token (signature, both internal and public issuer,
audience, expiry), then resolves the caller's tenant/team/role from `user_assignments`, keyed on
the stable IdP **`sub`** (a verified email may bind an assignment once on first login).

**Authorization is data-driven.** Each role carries a capability set (skills, tools, readable /
writable namespaces, allowed model regions, summary cap, runtime flag). That map is pushed into
OPA's `data.sentinel.rbac` document, and a single generic Rego policy evaluates every action
against it. Adding a tenant or role, or editing governance, is a data change synced to OPA —
**the policy code never changes.** Every governance mutation is written to the audit ledger.

**Planes.** Command plane (FastAPI: `/v1/ask`, WebSocket, admin API), Trust plane (OIDC, PDP,
values cascade, encrypted hash-chained audit, telemetry), Agent gateway (skills, tools, model
routing), Blueprint plane (signed skill manifests, capability templates), Runtime cell plane
(network-isolated Docker execution), Memory plane (tenant-scoped pgvector/keyword store). A React
SPA fronts it all over HTTP + OIDC.

---

## 3. Original audit findings — all resolved

The v0.3.0→v0.4.0 hardening pass closed every critical, high and medium finding. Condensed:

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| C1 | Critical | PDP queried an undefined `result` document → every action 403'd | Fixed |
| C2 | Critical | Cross-tenant isolation check was tautological | Fixed (then generalised in v0.5.0) |
| H1–H2 | High | `/admin/bootstrap` and `/v1/audit/*` unauthenticated; audit leaked all tenants | Fixed (guarded + tenant-scoped) |
| H3 | High | WebSocket token passed in the URL query string | Fixed (header / first-frame auth) |
| H4 | High | `.env` committed, no `.gitignore`, `.pyc` shipped | Fixed |
| H5 | High | `change-me` secrets silently usable in production | Fixed (boot-time guard) |
| H6 | High | Skill signatures / per-tenant enablement never verified | Implemented (then upgraded to Ed25519 in v0.9.0) |
| M1–M13 | Medium | No tests, no DB pooling, blocking DB in async, inert model routing, broken Azure adapter, dead runtime code, no structured logging/retries/rate limiting, unbounded audit verify, no migrations, JWKS races, no readiness probe | All implemented/fixed |
| L1–L4 | Low | Entrypoint mismatch, dead secrets code, hardcoded values cascade, unused pgvector | Fixed (L4 addressed by v0.9.0 semantic memory) |

---

## 4. Capabilities added after the audit (v0.5.0 → v1.0.0)

| Capability | Version | Notes |
|---|---|---|
| App-DB-centric RBAC + generic data-driven OPA | 0.5.0 | Keycloak authn-only; capability templates; OPA data sync; auto-migrations on startup |
| React SPA + Keycloak OIDC login | 0.7.0 | Vite app served by nginx; host-agnostic (web today, Tauri desktop later) |
| Add Tenant (API + UI) | 0.6.0 / 0.7.0 | New tenant gets the same shape as seeded ones; enforceable immediately |
| Add Role from template (API + UI) | 0.8.0 | Instantiate/delete roles per tenant |
| Governance editor (API + UI) | 0.8.0 | Edit a role's capabilities; re-syncs OPA; enforced live |
| Users & assignments (API + UI) | 0.8.0 | Assign identities to tenant/role; optional Keycloak login provisioning |
| Test console (UI) | 0.7.0 | Run a governed `/v1/ask`; view the per-action audit trace |
| Ed25519 skill signing | 0.9.0 | Asymmetric public-key verification; signing CLI |
| Semantic memory (pgvector) | 0.9.0 | Opt-in embeddings; tenant-filtered vector search; keyword fallback |
| Distributed rate limiting (Redis) | 0.9.0 | Shared cross-replica limiter; fails open |

---

## 5. Security posture

The platform now exhibits the governance properties it advertised. Identity is authenticated by a
hardened IdP and never trusted blindly; authorization is owned by the application and enforced by a
fail-closed PDP for every action; the identity→tenancy mapping is keyed on the stable `sub`, not a
mutable email; the admin / governance-write surface is authenticated and every change is recorded
in the encrypted, hash-chained audit ledger; audit reads are tenant-scoped; skill manifests are
verified with an asymmetric public key (no shared secret to distribute); prompt-injection from
untrusted tool output cannot escalate privileges (demonstrated as a recorded `deny`); and the audit
chain is independently verifiable and tamper-evident.

---

## 6. Verification evidence

- **Python tests:** 65 passing — production secret guard, values cascade, model routing, encrypted
  audit hash-chain (link integrity + tamper detection), PDP default-deny + cross-tenant denial,
  RBAC capability resolution, identity/sub binding, admin tenant/role/governance/user operations,
  Ed25519 sign/verify (+ tamper + wrong-key), Redis & in-process rate limiters (+ fail-open), and
  semantic-vs-keyword memory routing with the tenant filter ahead of ranking.
- **OPA policy tests:** generic policy over injected `data.sentinel.rbac` (cross-tenant denial,
  role-scoped writes, region residency, unknown-role denial, runtime network policy).
- **Lint & build:** `ruff` clean; the React SPA builds; the FastAPI app constructs with all routes.
- **Live end-to-end:** browser login, dynamic tenant/user creation with auto-provisioned login, a
  real governed LLM answer via Ollama, and a live governance change reflected in enforcement.

---

## 7. Remaining recommendations (seams after v1.0.0)

These are the honest next steps toward a certified production deployment:

1. **Full Sigstore** — keyless OIDC signing (Fulcio) + a Rekor transparency log, beyond the current
   asymmetric Ed25519 scheme.
2. **Semantic memory coverage** — embeddings are computed only on new writes; add a re-embed job so
   pre-existing/seeded memories become vector-searchable, and make the embedding dimension configurable.
3. **Native async DB driver** — the threadpool offload is correct; an async psycopg path raises the
   concurrency ceiling.
4. **Runtime isolation** — move runtime cells off the raw Docker socket to rootless Docker /
   gVisor / Kata / Firecracker, or Kubernetes Pod Security.
5. **Admin authn upgrade** — replace the shared-secret admin token with an OIDC `platform-admin`
   role or mTLS.
6. **Secrets & deployment** — real Vault/KMS (not dev mode), production OIDC client lifecycle, and
   Kubernetes/Helm/Terraform for multi-replica deployment (the Redis limiter is ready for it).
7. **Audit durability** — replicate the ledger to WORM/SIEM; per-tenant CMK/BYOK.
8. **Cost controls** — per-tenant/risk-tier token budgets in the model router.
9. **Pre-deployment** — load/performance testing, dependency & image scanning with SBOMs,
   secret-rotation runbooks, and a third-party penetration test.

---

## 8. Run & test (quick reference)

```bash
bash scripts/setup-host.sh        # host CLI prerequisites (jq/curl/zip)
cp .env.example .env
docker compose up -d --build      # migrations auto-apply; RBAC syncs to OPA
./scripts/wait-for-stack.sh && ./scripts/bootstrap.sh
# Web UI:  http://localhost:5173   (log in as jane / password)

pip install -e ".[dev]" && pytest -q     # 65 tests
opa test deploy/opa -v                    # policy tests
ruff check src tests                      # lint
```
