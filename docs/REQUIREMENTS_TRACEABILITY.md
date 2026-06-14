# Requirements Traceability

| Requirement area | Implementation |
|---|---|
| OIDC identity | Keycloak realm, JWKS JWT validation in `auth.py` |
| SCIM lifecycle | SCIM endpoint scaffold and tenant fixture provisioning |
| Tenant claim required | `auth.py`, OPA `valid_tenant_claim`, DB tenant filters |
| Cross-tenant isolation | Postgres `tenant_id`, PDP input resource tenant, memory queries require tenant |
| Role-derived capabilities | Keycloak roles/groups, values resolver, OPA rules |
| Signed skill registry | YAML manifest with signature field; production seam for Sigstore/KMS signing |
| PDP every action | `policy.decide` called for skill, memory, tool, model, runtime |
| Policy as code | `deploy/opa/aegis.rego`; Cedar sketch included |
| Values cascade | `values.py`, fixture values, summary clamping |
| Model router | `models.py`, `configs/model_registry.yaml` |
| Privacy gateway pattern | model prompt boundary + policy hook; extend with de-identification processor |
| Audit chain | encrypted Postgres audit events with hash chain |
| Observability | OpenTelemetry SDK + collector + Jaeger |
| Subagent seam | documented in ADR-008 and extension seam; not fully implemented |
| Runtime isolation | Docker Runtime Cell hardening contract |
| Production memory | PostgreSQL + pgvector schema |
