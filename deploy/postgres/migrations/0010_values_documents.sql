-- 0010: values documents per scope (organization / department / team / role / individual).
-- These are the human-authored prose statements of values at each cascade level.
-- Distinct from values_rules (the structured rule rows the PDP evaluates) — these are
-- the narrative documents the admins write, that PEOPLE read to understand the rules.

CREATE TABLE IF NOT EXISTS values_documents (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_type   TEXT NOT NULL CHECK (scope_type IN
                ('organization','department','team','role','individual')),
  tenant_id    TEXT REFERENCES tenants(tenant_id) ON DELETE CASCADE,  -- NULL for organization
  scope_id     TEXT,           -- team_id, role_id, user_email; NULL for organization
  title        TEXT NOT NULL,
  body_md      TEXT NOT NULL,
  author_user  TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_values_documents_scope
    ON values_documents(scope_type, tenant_id, scope_id);
CREATE INDEX IF NOT EXISTS idx_values_documents_tenant
    ON values_documents(tenant_id);

-- A single org-level doc is allowed; no duplicate (scope_type, tenant_id, scope_id) inside a tenant
CREATE UNIQUE INDEX IF NOT EXISTS uq_values_documents_scope
    ON values_documents(COALESCE(tenant_id,''), scope_type, COALESCE(scope_id,''));
