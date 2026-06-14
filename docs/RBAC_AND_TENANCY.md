# RBAC & Tenancy (v0.5.0)

## Model

Authentication and authorization are separated:

- **Keycloak authenticates** — it proves *who* a caller is and issues a signed token
  (`sub`, `email`, ...). It no longer governs *what* they can do.
- **The application database authorizes** — it is the single source of truth for tenancy
  and role capabilities. This is what makes adding tenants/roles a data change with no
  Keycloak group juggling.

### Tables (migration `0002_rbac.sql`)

- `role_templates(template_id, display_name, capabilities)` — the catalog of reusable
  role archetypes (seeded: `analyst`, `lead`, `viewer`).
- `roles(..., template_id, capabilities)` — a tenant's role, instantiated from a template.
- `user_assignments(sub, user_email, tenant_id, team_id, role_id, bound_at)` — maps an
  authenticated identity to its tenancy/role. Keyed on **`sub`** (the stable IdP subject);
  `email` is a display label and a one-time binding key.

### Capability shape

```json
{ "skills": ["summarise-with-memory"], "tools": ["external_lookup"],
  "readable_namespaces": ["analyst-notes"], "writable_namespaces": ["analyst-notes"],
  "allowed_model_regions": ["AC1"], "max_summary_words": 200, "runtime_exec": false }
```

## How authorization flows

1. `auth.validate_token` verifies the token (signature, issuer — both internal and public,
   audience, expiry), then calls `rbac.resolve_assignment(sub, email, email_verified)` to
   look up the caller's tenant/team/role from the DB.
   - Lookup is by `sub`. If none and `SAF_ALLOW_EMAIL_BINDING=true`, a **verified** email may
     claim a not-yet-bound assignment once, stamping its `sub` for all future lookups.
2. `values.resolve_values` loads that role's capabilities from the DB.
3. Every action is checked by OPA against `data.sentinel.rbac[tenant][role]`, which the app
   keeps in sync via `rbac.sync_opa` (a single generic policy — `deploy/opa/aegis.rego` —
   evaluates all actions, so new roles/tenants never require Rego edits).

## Identity binding for new users

A person still needs a Keycloak login to authenticate. Onboarding is two parts: a Keycloak
identity (so they can log in) and a `user_assignments` row (their tenant/role). For the demo,
jane/lee/ben are seeded by email and bind their `sub` on first login.

## Upgrading an existing deployment to 0.5.0

Migrations run automatically on API startup (`SAF_RUN_MIGRATIONS_ON_STARTUP=true`), so the
new tables/columns are created on the next `docker compose up`. Then **re-run bootstrap once**
to stamp role capabilities, seed user assignments, and push RBAC to OPA:

```bash
docker compose up -d --build
./scripts/wait-for-stack.sh
./scripts/bootstrap.sh      # idempotent: seeds templates/caps/assignments + syncs OPA
```

## Relevant settings

| Env var | Default | Purpose |
|---|---|---|
| `SAF_ALLOW_EMAIL_BINDING` | `true` | Allow a verified email to claim an unbound assignment once. |
| `SAF_ALLOW_GROUP_FALLBACK` | `false` | Transitional: derive tenant/role from the token group path if no DB assignment. |
| `SAF_RUN_MIGRATIONS_ON_STARTUP` | `true` | Apply pending SQL migrations on API startup. |
| `SAF_SYNC_OPA_ON_STARTUP` | `true` | Push the RBAC capability map to OPA on startup. |
| `SAF_CORS_ORIGINS` | `http://localhost:5173` | Allowed browser origins (for the upcoming React SPA). |
