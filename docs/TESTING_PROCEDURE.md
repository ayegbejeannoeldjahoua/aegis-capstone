# Governance Testing Procedure

Use these commands from the repository root.

## Seed Or Reset

Regenerate the fixture and inspect counts without touching the database:

```bash
python3 scripts/seed-governance-test-data.py --write-fixture --dry-run
```

Seed the live database idempotently:

```bash
python3 scripts/seed-governance-test-data.py --reset-label-first
```

Optionally create Keycloak logins for the new synthetic users:

```bash
export AEGIS_TEST_USER_PASSWORD='password'
python3 scripts/seed-governance-test-data.py --reset-label-first --provision-logins
```

Reset only the augmented rows:

```bash
python3 scripts/reset-governance-test-data.py --label capstone-demo-2026
```

## Traffic Generation

Dry-run a 20-turn plan without model calls:

```bash
python3 scripts/generate-governance-traffic.py --turns 20 --label smoke --dry-run
```

Run a cost-controlled live pass with an existing bearer token:

```bash
python3 scripts/generate-governance-traffic.py \
  --base-url http://localhost:8080 \
  --admin-token "$AEGIS_ADMIN_TOKEN" \
  --users jane@acmecp.example kim@acmecp.example pat@acmecp.example priya@it.example jane@finsvc.example \
  --turns 200 \
  --max-turns 200 \
  --label capstone-demo-2026
```

Reports are written to `exports/governance-traffic-<label>.json`. The `exports/` directory is generated
runtime output and should not be committed.

## Reversible Negative Tests

Temporarily deny analyst access to the assistant skill:

```bash
python3 scripts/seed-governance-test-data.py --reset-label-first
python3 - <<'PY'
from aegis_fabric.db import BYPASS_TENANT, with_tenant_scope
with with_tenant_scope(BYPASS_TENANT) as conn:
    conn.execute("""
      UPDATE roles
      SET capabilities = jsonb_set(capabilities::jsonb, '{skills}', '["qa-over-docs"]'::jsonb)
      WHERE role_id='analyst-low-budget'
    """)
PY
```

Restore:

```bash
python3 scripts/seed-governance-test-data.py --reset-label-first
```

Temporarily force a low budget:

```bash
python3 scripts/seed-governance-test-data.py --reset-label-first
```

The `analyst-low-budget` template already sets `token_budget_per_day=100` and `max_output_tokens=512`.

Temporarily test denied egress:

```bash
python3 scripts/seed-governance-test-data.py --reset-label-first
```

Use any `governance-no-egress@<tenant-domain>` user and request a blocked external domain. Restore by rerunning
the seed command above.

Temporarily test tampered skill manifests:

```bash
cp configs/skills/assistant.skill.yaml /tmp/assistant.skill.yaml.backup
# Edit a non-secret descriptive field, run the signature verification scenario, then restore:
cp /tmp/assistant.skill.yaml.backup configs/skills/assistant.skill.yaml
```

Do not commit temporary manifest edits.

## Validation

```bash
python3 -m compileall -q src
python3 -m pytest tests/test_augmented_fixtures.py -q
bash -n scripts/seed-governance-test-data.py || true
bash -n scripts/generate-governance-traffic.py || true
docker compose -f docker-compose.yml config
docker compose -f docker-compose.yml -f deploy/gcp/docker-compose.production.yml --env-file deploy/gcp/.env.production.example config
```

The `bash -n` commands are retained for compatibility with the requested checklist even though these files are
Python scripts; use `python3 -m py_compile scripts/seed-governance-test-data.py scripts/generate-governance-traffic.py`
for actual Python syntax validation.

## VM Deployment And Seed

After the changes are committed and pushed:

```bash
git push origin main
```

On the VM:

```bash
cd /opt/aegis/aegis_platform
sudo git fetch origin main
sudo git reset --hard origin/main
sudo bash deploy/gcp/redeploy.sh
python3 scripts/seed-governance-test-data.py --reset-label-first
python3 scripts/generate-governance-traffic.py --turns 20 --label smoke --dry-run
```

To also provision Keycloak logins:

```bash
export AEGIS_TEST_USER_PASSWORD='password'
python3 scripts/seed-governance-test-data.py --reset-label-first --provision-logins
```
