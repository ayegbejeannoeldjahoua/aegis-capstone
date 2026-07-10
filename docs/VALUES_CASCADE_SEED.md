# Values Cascade Seed

`configs/fixtures/values_cascade_seed.yaml` contains the structured seed data extracted from
`aegis_values_cascade_seed_document.docx`.

The seed is transformed by `scripts/seed-governance-test-data.py` into `values_documents` rows, which are the rows
used by the runtime values cascade and the `values.apply` audit event.

## Scope Mapping

- Organization rows remain reference rows. Existing organization values are not overwritten during database seeding.
- Tenant and department rows are stored as one `department` document per tenant because `values_documents` is keyed by
  tenant, scope type, and scope ID.
- Team rows use existing Aegis team IDs such as `research`, `operations`, `platform`, `security`, and `infrastructure`.
- Role rows use `scope_id = role_id`.
- Individual rows use `scope_id = user_email`.

## Commands

Preview counts without touching the database:

```bash
python3 scripts/seed-governance-test-data.py --dry-run
```

Regenerate the generated governance fixture with the values cascade rows merged:

```bash
python3 scripts/seed-governance-test-data.py --write-fixture --dry-run
```

Seed a non-production database:

```bash
python3 scripts/seed-governance-test-data.py --reset-label-first
```

Reset rows created for the default fixture label:

```bash
python3 scripts/reset-governance-test-data.py
```

Do not run these commands against a live production database unless the target environment is intentionally prepared for
governance acceptance-test data.
