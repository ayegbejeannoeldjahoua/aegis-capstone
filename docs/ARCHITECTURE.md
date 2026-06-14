# Architecture

## Production-mode mapping

This system extracts and generalizes five classes of source patterns:

1. **Sandbox/runtime control:** gateway-managed workloads, runtime drivers, network and filesystem policy, managed inference routing, request-scoped credentials.
2. **Agent gateway:** channel/session concepts, model catalog, provider adapters, fallback handling, skill and plugin manifests, strict configuration validation.
3. **Blueprinting/onboarding:** pinned runtime images, profile-driven provider setup, local/hosted inference profiles, hardening scripts, sandbox policies.
4. **Workflow discipline:** role-separated agents, artifact contracts, append-only ledgers, restricted policies, stop conditions.
5. **Enterprise governance:** OIDC, SCIM, tenancy, PDP, values cascade, signed registry, memory governance, audit, traceability, failure-closed behavior.

## Planes

```text
Clients and Channels
  CLI, API, future web/mobile/Slack/Teams connectors

Command Plane
  FastAPI service, request intake, streaming API, session orchestration

Trust Plane
  Keycloak OIDC, SCIM provisioning, OPA PDP, values cascade, capability broker, audit, telemetry

Agent Gateway
  skill invocation, tool calls, model routing, provider failover, future channel adapters

Runtime Cells
  Docker/Kubernetes/microVM-style isolated execution. Current backend: Docker with a hardened contract.

Memory Plane
  PostgreSQL + pgvector, tenant-filter-before-similarity, markdown/frontmatter portability.
```

## Security invariants

- No request without OIDC token and tenant claim.
- No memory/tool/model/runtime action without a PDP decision.
- No cross-tenant memory or inference channel.
- Model routing is region/provider/purpose governed.
- Tool/retrieval/memory content is untrusted input.
- Runtime Cells run non-root, no-new-privileges, cap-drop all, read-only root, network default-deny.
- Audit is encrypted and hash-chained.
- Failure-closed: if IdP, PDP, or audit is unavailable, guarded operations deny.

## Production replacement seams

- Docker socket backend -> Kubernetes/gVisor/Kata/Firecracker runtime controller.
- Compose Keycloak -> enterprise IdP/managed Keycloak.
- Vault dev -> production Vault/KMS/HSM.
- Local Postgres -> managed HA Postgres with backups, PITR, encryption, replicas.
- Local OTel collector -> enterprise observability backend.
- Rego bundle files -> policy CI/CD with signed bundles.
