# Aegis AI Governance Platform

A governed, multi-tenant enterprise AI agent platform. One login page for everyone,
chat for end users, admin console for the two designated platform-admins per tenant.

This tree is a working implementation — backend, frontend, database, identity, policy
engine, audit ledger — all wired and runnable locally with `bash run_aegis.sh up`.

## What's in here

```
aegis_platform/
  src/sentinel_fabric/     # FastAPI backend (39 modules)
  frontend/                # React UI: login, chat, admin console
  configs/                 # fixture, channels, skills, blueprints, model registry
    fixtures/
      tenant_fixture.yaml  # 8 tenants, 40 roles, 20 users, 63 memories
  deploy/
    postgres/              # init.sql + 9 migrations
    keycloak/realm-aegis.json
    opa/                   # Rego policies + tests
  scripts/                 # bootstrap, demos, backup/restore
  tests/                   # 65 Python tests + OPA tests
  docker-compose.yml
  run_aegis.sh             # orchestration entry point
  AEGIS_README.md          # this file
```

## Quickstart

```bash
cd aegis_platform
bash run_aegis.sh up
```

When `up` finishes:

- Open the **login page** at <http://localhost:5173> — Keycloak signs everyone in.
- After login you land on **Home** with two cards:
  - **Chat** — opens the assistant. Everyone gets this.
  - **Admin & Governance Console** — visible only if your role is `platform-admin`.

## Login credentials

Password is `password` for every account in the demo.

### Platform admins (the "two IT people" pattern, per tenant)

These users see the admin console with Tenants / Users / Governance / Audit / Models / MCP pages.

| Tenant | Admin 1 | Admin 2 |
|---|---|---|
| Acme Corp Research | `pat@acmecp.example` | `kim@acmecp.example` |
| Beta Holdings | `pat@betago.example` | `kim@betago.example` |
| Gamma Consulting | `pat@gammac.example` | `kim@gammac.example` |
| Finance Dept | `pat@finsvc.example` | `kim@finsvc.example` |
| HR & People Ops | `pat@hrops.example` | `kim@hrops.example` |
| EU Sales | `pat@saleseu.example` | `kim@saleseu.example` |
| Core Engineering | `pat@engcore.example` | `kim@engcore.example` |
| Legal & Compliance | `pat@legalco.example` | `kim@legalco.example` |

### End users (sample)

Canonical synthetic users seeded per tenant, e.g.:

- `jane@acmecp.example` — analyst, Acme Corp Research
- `ben@betago.example` — analyst, Beta Holdings

## Features the platform delivers

| Capability | Where it lives |
|---|---|
| Login page for everyone | Keycloak OIDC at `/realms/aegis`; same URL for end users and admins |
| Chat interface for everyone | `frontend/src/pages/Chat.jsx` → `POST /v1/ask` |
| Admin console only for platform-admins | `frontend/src/Console.jsx`; gated on `admin_scope === 'platform'` |
| Register users via admin console | `Users.jsx` + `admin /users` endpoints; auto-provisions Keycloak login |
| Roles + capabilities configurable | `Governance.jsx` + `PUT /admin/tenants/{tid}/roles/{rid}/capabilities` |
| Admin-selectable global model | `Models.jsx` + `platform_settings.default_model`; supports OpenAI / Azure / NVIDIA / Ollama / vLLM |
| Token tracking → FinOps | `usage.py` — Redis-backed daily token budget per role; `/v1/ask` denies when over |
| Audit ledger (encrypted, hash-chained) | `audit.py` + `audit_events` table; admin can re-verify whole chain |
| Multi-tenant isolation | OPA generic policy + per-tenant capability JSONB pushed at startup |

## Backing services (all real, all in docker-compose)

| Service | Image | Stores |
|---|---|---|
| PostgreSQL | `pgvector/pgvector:pg16` | tenants, teams, roles + capabilities, user_assignments, values_rules, memories + vector(384) embeddings, audit_events, platform_settings, sessions |
| MongoDB | `mongo:7` | document corpus for retrieval |
| Keycloak | `keycloak:26.1` (realm `aegis`) | user accounts, passwords, OIDC tokens |
| Redis | `redis:7-alpine` | FinOps counters, rate limits |
| Vault | `vault:1.17` (dev) | secrets (model API keys, signing keys) |
| OPA | `opa:0.70.0` | policy decisions |
| OTel + Jaeger | latest | distributed traces (`http://localhost:16686`) |

## Verifying it works

```bash
bash run_aegis.sh status
```

Expected (after bootstrap):
- tenants ≥ 8
- user_assignments ≥ 20  (16 platform-admins + sample end users)
- memories ≥ 60 (14 docs × subset of tenants)

Open <http://localhost:5173>, log in as `pat@acmecp.example`, click **Chat**, ask:

> *"Summarise the customer call transcript notes."*

The assistant retrieves the synthetic customer call transcript (with fake email and
phone), the PII classifier flags it as `confidential`, the audit ledger records every
gate, and the answer comes back stamped with the trace_id.

Now click **Console → Models**. Change the active model from the default to a different
provider. The next chat call uses the new model — no restart needed.

## End-to-end test scenarios

| Test | How to run |
|---|---|
| PII anonymisation | Ask the chat to summarise the customer call. The retrieved memory contains `marcus.lee.synthetic@example-co.test` and `+1-555-0173-4419`. The classifier output and audit row should label it ≥ `confidential`. |
| FinOps limit | Log in as `jane@acmecp.example` (analyst). Spam high-token prompts until the daily budget hits zero — next call denies with `budget_exceeded`. Check Console → Audit. |
| Cross-tenant gate | As `jane@acmecp.example`, try to read a memory under `tenant-betago`. PDP denies — tenant boundary is enforced. |
| Injection resistance | Submit one of the `injection_canary_*` documents as a prompt. The chokepoint must not write an extra memory to `team-decisions`. |
| Audit hash chain | Console → Audit → Verify. Whole chain re-derives cleanly. |
| User registration | Console → Users → Add. Fill email, tenant, role. SAF provisions the Keycloak login automatically; new user can sign in. |
| Capability editing | Console → Governance → click a role → change `max_read_classification` from `confidential` to `internal`. Save. Next chat call by that role denies on `confidential` reads. |
| Model swap | Console → Models → select another provider. Next chat call uses the new model. |

## How to regenerate the fixture

The fixture is built from the 58-table synthetic dataset and the 14 generated
documents elsewhere in this workspace:

```bash
cd ../saf_integration
python3 generate_saf_fixture.py \
    --synth-dir ../synthetic_governance_data \
    --docs-dir  ../aegis_integration/documents \
    --out       ../aegis_platform/configs/fixtures/tenant_fixture.yaml
```

Then `bash run_aegis.sh reseed`.

## How to rebrand further (if you ever want to change the name again)

User-visible Aegis strings live in:

- `frontend/src/Home.jsx`, `Console.jsx`, `pages/Chat.jsx`, `pages/Models.jsx`, etc.
- `frontend/index.html`
- `frontend/public/config.js`
- `src/sentinel_fabric/main.py` (FastAPI app title)
- `README.md`, `AEGIS_README.md`

Internal env var prefixes (`SAF_*`), Python module name (`sentinel_fabric`), and the OPA
package name (`sentinel.authz`) were intentionally left untouched — they're not
user-visible, and changing them would touch hundreds of files without changing any
behaviour or the user experience.

## Stop / restart / reset

```bash
bash run_aegis.sh down            # stop containers (data preserved)
bash run_aegis.sh up              # start again
bash run_aegis.sh reseed          # re-bootstrap (idempotent)
bash run_aegis.sh nuke            # destroys ALL data
```
