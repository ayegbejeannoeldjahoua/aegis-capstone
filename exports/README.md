# exports/

Generated, NOT hand-edited. The API's background exporter (export_state.py) writes
`seed-state.sql` here whenever a governance change is detected (new tenant/role/team,
governance edit, user assignment, etc.). It is an idempotent SQL seed that captures the
current structure + governance + user assignments — but NOT secrets and NOT sub bindings.

Bare-scratch reinstall workflow:
1. Keep this folder in your working copy (it's bind-mounted into the API container).
2. After a fresh `docker compose up -d --build` + `bash scripts/bootstrap.sh`, replay the
   latest state with:  `bash scripts/import-state.sh`
3. For full fidelity (passwords, documents, bindings) use `scripts/backup.sh` /
   `scripts/restore.sh` instead — those capture everything via pg_dump + mongodump.
