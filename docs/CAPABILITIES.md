# Role capabilities (v1.1.0)

A role's `capabilities` JSONB drives authorization. Each field is enforced at a specific point;
the capability map is synced to OPA's `data.sentinel.rbac` so the generic policy evaluates it.

## Schema & enforcement

| Field | Type | Governs | Enforced at |
|---|---|---|---|
| `skills` | list | invokable skills | OPA `skill.invoke` |
| `tools` | list | callable tools | OPA `tool.call` |
| `readable_namespaces` / `writable_namespaces` | list | memory access | OPA `memory.read`/`memory.write` |
| `max_read_classification` | enum | highest classification readable | `memory.read` row filter (data layer) |
| `max_write_classification` | enum | highest classification writable | OPA `memory.write` (writable_classifications) |
| `allowed_model_regions` | list | data residency | OPA `model.call` |
| `allowed_providers` | list | permitted providers (empty=any) | OPA `model.call` + router |
| `allowed_model_ids` | list | permitted models (empty=any) | router |
| `max_model_risk_tier` | T1/T2/T3 | highest model risk tier | router |
| `require_local_above_classification` | enum | data ≥ this ⇒ local model only | router |
| `max_summary_words` | int | output length | values cascade |
| `runtime_exec` | bool | sandbox code execution | OPA `runtime.exec` |
| `admin_scope` | none/tenant/platform | administrative reach | `admin_principal` |
| `can_manage_users` / `can_manage_roles` / `can_edit_governance` / `can_register_skills` | bool | admin operations | admin endpoints |
| `audit_scope` | none/own/team/tenant/all | audit visibility | audit endpoints |

Classification order: `public < internal < confidential < restricted`. Risk order: `T1 < T2 < T3`.

## Seeded templates

`analyst`, `lead`, `viewer` (end users), `tenant-admin` (manage own tenant), `platform-admin`
(cross-tenant). New roles are instantiated from a template and may override any field.

## Admin authorization

The admin/governance API accepts EITHER the shared `X-Admin-Token` (super-admin / ops) OR an OIDC
user whose role grants an `admin_scope`. Tenant-admins are confined to their own tenant; platform
admins are unconstrained; creating tenants and editing global templates require platform scope.

## Roadmap (not yet implemented)

Tier 2: cost/token budgets, runtime network/resource caps, `deletable_namespaces`/retention, output
DLP/PII redaction, zero-trust context (`mfa_required`, `ip_allowlist`, `allowed_hours`). Tier 3:
human-in-the-loop approvals + dual control, vision/tool-calling/temperature, citation requirements.
