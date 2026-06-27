# Augmented Governance Test Data

This repository includes an additive synthetic fixture for governance acceptance testing:

- `configs/fixtures/governance_test_fixture.yaml`
- `scripts/seed-governance-test-data.py`
- `scripts/reset-governance-test-data.py`
- `scripts/generate-governance-traffic.py`

The baseline fixture remains `configs/fixtures/tenant_fixture.yaml`. The augmented fixture is labeled
`capstone-demo-2026` and is safe to seed repeatedly.

## Target Counts

Baseline plus augmentation yields:

| Area | Baseline | Added | Final |
| --- | ---: | ---: | ---: |
| Tenants | 9 | 0 | 9 |
| Users | 30 | 72 | 102 |
| Role templates | 5 | 7 test-only | 12 |
| Memory documents | 63 | 207 | 270 |
| Pending approvals | 0 fixture rows | 18 | 18 |
| ISA rows | 0 fixture rows | 54 | 54 |
| Turn feedback rows | 0 fixture rows | 54 | 54 |
| Values documents | baseline docs | 168 scoped docs | org, department, team, role, individual |

## Test-Only Roles

The seeder adds these data-driven templates without changing production defaults:

| Template | Base | Purpose | Key delta |
| --- | --- | --- | --- |
| `analyst-no-egress` | `analyst` | Egress denial | `egress_domains=[]` |
| `analyst-low-budget` | `analyst` | FinOps refusal | `token_budget_per_day=100`, `max_output_tokens=512` |
| `auditor` | `viewer` | Tenant audit browsing | `audit_scope=tenant`, `can_view_traces=true`, no mutation rights |
| `approval-reviewer` | `lead` | Approval queue tests | `can_approve=tenant`, no user/role management |
| `restricted-reader` | `lead` | Restricted positive control | `max_read_classification=restricted`, `pii_scope=full`, `can_export=false` |
| `runtime-denied-engineer` | `viewer` | Runtime denial | no `code_exec`, `runtime_exec=false` |
| `runtime-python-engineer` | `lead` | Runtime positive control | `runtime_exec=true`, `runtime_network=none`, `allowed_runtime_languages=['python']` |

Each tenant receives one role instance for every test-only template and eight synthetic user assignments.

## Corpus Coverage

The combined corpus reaches 30 memory documents per tenant and 5 documents in each namespace:

- `analyst-notes`
- `team-decisions`
- `research-log`
- `case-notes`
- `policy-drafts`
- `transcripts`

The augmented rows include public, internal, confidential, and restricted classifications; prompt-injection
canaries; PII-bearing documents; and cross-tenant decoys. Sensitive-looking data uses `.example` domains,
555 phone numbers, `TEST-` identifiers, and body text that identifies it as synthetic.

## Idempotency

The seed script uses stable keys:

- Role templates: `template_id`
- Tenant roles: `(tenant_id, role_id)`
- User assignments: `(lower(user_email), tenant_id)`
- Memories: `frontmatter.fixture_id`
- Values documents: existing scoped unique index
- Pending actions and traffic rows: `fixture_label`
- ISA and feedback traffic: trace ID prefix `gov-capstone-demo-2026-`

Run the seed more than once with the same label to refresh rows without duplicating memories.

## Keycloak Logins

The seeder does not commit passwords. To provision logins for the new synthetic users, set a temporary
operator-provided password at runtime:

```bash
export AEGIS_TEST_USER_PASSWORD='password'
python3 scripts/seed-governance-test-data.py --provision-logins
```

Without `--provision-logins`, only database assignments are seeded.
