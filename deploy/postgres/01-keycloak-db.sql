-- Keycloak (production mode) stores its users, credentials and realm in Postgres so they
-- persist across container recreation. This creates a dedicated `keycloak` database on the
-- shared Postgres instance. Runs only when the postgres_data volume is first initialised
-- (docker-entrypoint-initdb.d). Idempotent: it no-ops if the database already exists.
--
-- For an EXISTING deployment (postgres_data already populated) this file will NOT run, so
-- create the database once by hand:
--   docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
--     -c "CREATE DATABASE keycloak;"
SELECT 'CREATE DATABASE keycloak'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'keycloak')\gexec
