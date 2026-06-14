-- v1.20 BR-ISO-05: Postgres row-level-security backstop.
-- This is the THIRD isolation layer beneath the PDP (OPA) and the per-query
-- tenant filter the application already enforces. Even if both upper layers
-- fail open, Postgres refuses cross-tenant reads/writes when the per-
-- connection `app.tenant_id` GUC doesn't match the row's tenant_id.
--
-- The application sets `app.tenant_id` per transaction via the
-- db.with_tenant_scope() context manager. Admin operations that legitimately
-- span tenants (export, fixture seed, cross-tenant audit) set it to '*'
-- (the bypass marker).
--
-- FORCE ROW LEVEL SECURITY makes RLS apply to table owners too -- without
-- it, the app's connection role bypasses RLS silently.

BEGIN;

ALTER TABLE memories     ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories     FORCE  ROW LEVEL SECURITY;

ALTER TABLE sessions     ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions     FORCE  ROW LEVEL SECURITY;

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE  ROW LEVEL SECURITY;

ALTER TABLE isas         ENABLE ROW LEVEL SECURITY;
ALTER TABLE isas         FORCE  ROW LEVEL SECURITY;

-- Drop in case of re-run on an already-migrated DB.
DROP POLICY IF EXISTS tenant_isolation_memories     ON memories;
DROP POLICY IF EXISTS tenant_isolation_sessions     ON sessions;
DROP POLICY IF EXISTS tenant_isolation_audit_events ON audit_events;
DROP POLICY IF EXISTS tenant_isolation_isas         ON isas;

CREATE POLICY tenant_isolation_memories ON memories
  USING      (current_setting('app.tenant_id', true) IN (tenant_id, '*'))
  WITH CHECK (current_setting('app.tenant_id', true) IN (tenant_id, '*'));

CREATE POLICY tenant_isolation_sessions ON sessions
  USING      (current_setting('app.tenant_id', true) IN (tenant_id, '*'))
  WITH CHECK (current_setting('app.tenant_id', true) IN (tenant_id, '*'));

CREATE POLICY tenant_isolation_audit_events ON audit_events
  USING      (current_setting('app.tenant_id', true) IN (tenant_id, '*'))
  WITH CHECK (current_setting('app.tenant_id', true) IN (tenant_id, '*'));

CREATE POLICY tenant_isolation_isas ON isas
  USING      (current_setting('app.tenant_id', true) IN (tenant_id, '*'))
  WITH CHECK (current_setting('app.tenant_id', true) IN (tenant_id, '*'));

COMMIT;
