# Aegis AI Governance Platform — Production-Mode Enterprise Agent Platform

Aegis AI Governance Platform is a production-mode reference implementation for a governed, multi-tenant enterprise AI agent platform. It is designed to be runnable with real services and real model providers while still shipping with synthetic tenants/data for safe demonstrations.

The repository deliberately uses neutral names. It extracts and generalizes the strongest useful patterns from the source materials you studied:

- secure sandbox gateway / runtime-driver patterns,
- local-first gateway / session / skill / plugin / model-provider patterns,
- agent onboarding / blueprint / model-routing / sandbox-policy patterns,
- role-separated workflow and artifact handoff patterns,
- enterprise governance requirements: OIDC, SCIM, tenancy, PDP, values cascade, audit, traceability, and failure-closed controls.

## What this is

This is a deployable production-mode scaffold, not a certified production product. See `docs/PRODUCTION_READINESS_REVIEW.md` for a full critical review and the remediation applied in this build, and run `pytest -q` plus `opa test deploy/opa -v` for the test suite. It includes actual service wiring for:

- FastAPI Command Plane
- Keycloak OIDC IdP
- SCIM-like provisioning endpoints
- OPA policy engine with Rego policies
- PostgreSQL + pgvector memory tier
- Vault-compatible managed secrets
- Docker-isolated Runtime Cells
- encrypted hash-chained audit ledger
- OpenTelemetry traces/metrics/logs via collector
- selectable real model providers: OpenAI-compatible, NVIDIA-compatible, Ollama, vLLM, Azure OpenAI-compatible
- signed skill/agent blueprint manifests
- tenant/team/role/individual values cascade
- governed model routing with primary/fallbacks/regions (per-tenant cost budgets remain a seam)

## Core planes

```text
Command Plane
  API, request intake, session orchestration, streaming endpoints, client boundary.

Trust Plane
  OIDC, SCIM, tenancy, PDP, values cascade, capability broker, audit, telemetry.

Agent Gateway
  sessions, tools, skill invocation, channels, model selection, provider adapters.

Blueprint Plane
  signed skill manifests, model profiles, runtime cell profiles, deployment descriptors.

Runtime Cell Plane
  containerized sandbox execution with non-root, no-new-privileges, cap-drop, read-only root, network default-deny.

Memory Plane
  PostgreSQL/pgvector tenant-scoped memory with markdown/frontmatter portability.
```

## Production-mode services

```text
api             FastAPI command plane
postgres        PostgreSQL with pgvector
keycloak        OIDC identity provider
opa             policy decision point
vault           managed secrets backend, dev mode by default for local demonstration
otel-collector  OpenTelemetry collector
jaeger          trace viewer
runtime-cell    hardened image used for per-request isolated executions
ollama          optional local model provider profile
```

## Quick demo

```bash
cp .env.example .env
# edit .env and choose at least one model backend, e.g. Ollama or NVIDIA/OpenAI-compatible

docker compose up -d --build

./scripts/wait-for-stack.sh
./scripts/bootstrap.sh
./scripts/demo-happy-path.sh
./scripts/demo-denials.sh
./scripts/demo-audit-telemetry.sh
```

Open:

- API docs: http://localhost:8080/docs
- Keycloak: http://localhost:8081
- OPA: http://localhost:8181
- Jaeger: http://localhost:16686
- Vault: http://localhost:8200

## Production notes

Before real organizational deployment, replace local/demo settings with enterprise equivalents:

- Keycloak dev credentials with managed IdP or hardened Keycloak deployment.
- Vault dev server with production Vault/KMS/HSM.
- local Docker socket sandbox backend with rootless Docker, Kubernetes, gVisor, Kata, Firecracker, or an equivalent workload isolation backend.
- local compose with Kubernetes/Helm/Terraform.
- demo model keys with managed secret references and provider allowlists.
- demo self-signed/internal tokens with enterprise OIDC clients and SCIM lifecycle.

This package is intentionally explicit about those seams so the system can be examined and extended in an online repository.

## Real-time multi-user access

The API exposes both HTTP `/v1/ask` and WebSocket `/v1/ws/chat?token=...` so several users from different tenants/teams can connect concurrently with separate OIDC tokens, model choices, audit traces, and tenant-scoped memory. See `docs/STEP_BY_STEP_PRODUCTION_DEMO.md`.
