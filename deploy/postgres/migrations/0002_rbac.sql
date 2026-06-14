-- 0002: app-DB-centric RBAC (role templates, per-role capabilities, sub-keyed user assignments)
CREATE TABLE IF NOT EXISTS role_templates (
  template_id  TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE roles ADD COLUMN IF NOT EXISTS template_id  TEXT;
ALTER TABLE roles ADD COLUMN IF NOT EXISTS capabilities JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Identity -> tenancy/RBAC. Keyed on the IdP subject (sub); email is a display label and a
-- one-time binding key. `sub` is bound on first authenticated use (see auth.resolve_assignment).
CREATE TABLE IF NOT EXISTS user_assignments (
  assignment_id BIGSERIAL PRIMARY KEY,
  sub           TEXT UNIQUE,
  user_email    TEXT NOT NULL,
  tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  team_id       TEXT NOT NULL,
  role_id       TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  bound_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_user_assignments_email ON user_assignments(lower(user_email));
CREATE INDEX IF NOT EXISTS idx_user_assignments_sub   ON user_assignments(sub);
CREATE INDEX IF NOT EXISTS idx_roles_tenant            ON roles(tenant_id);
