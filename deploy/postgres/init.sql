CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tenants (
  tenant_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  region TEXT NOT NULL DEFAULT 'AC1',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS teams (
  tenant_id TEXT REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  team_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  PRIMARY KEY (tenant_id, team_id)
);

CREATE TABLE IF NOT EXISTS roles (
  tenant_id TEXT REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  role_id TEXT NOT NULL,
  team_id TEXT NOT NULL,
  PRIMARY KEY (tenant_id, role_id)
);

CREATE TABLE IF NOT EXISTS memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  namespace TEXT NOT NULL,
  author_user TEXT NOT NULL,
  author_scope TEXT NOT NULL,
  classification TEXT NOT NULL DEFAULT 'internal',
  retention_class TEXT NOT NULL DEFAULT 'standard',
  policy_version TEXT NOT NULL,
  values_version TEXT NOT NULL,
  frontmatter JSONB NOT NULL DEFAULT '{}'::jsonb,
  body TEXT NOT NULL,
  body_hash TEXT NOT NULL,
  embedding vector(384),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memories_tenant_namespace ON memories(tenant_id, namespace, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_frontmatter ON memories USING GIN(frontmatter);

CREATE TABLE IF NOT EXISTS audit_events (
  sequence_id BIGSERIAL PRIMARY KEY,
  trace_id TEXT NOT NULL,
  span_id TEXT,
  parent_span_id TEXT,
  tenant_id TEXT NOT NULL,
  subject TEXT NOT NULL,
  action TEXT NOT NULL,
  resource TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  values_version TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT,
  ciphertext BYTEA NOT NULL,
  nonce BYTEA NOT NULL,
  aad TEXT NOT NULL,
  event_hash TEXT NOT NULL UNIQUE,
  prev_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_events(trace_id, sequence_id);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_events(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS values_rules (
  tenant_id TEXT NOT NULL,
  scope_type TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  version TEXT NOT NULL,
  rules JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, scope_type, scope_id, version)
);

CREATE TABLE IF NOT EXISTS skill_registry (
  skill_id TEXT PRIMARY KEY,
  version TEXT NOT NULL,
  manifest JSONB NOT NULL,
  signature TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


CREATE TABLE IF NOT EXISTS sessions (
  session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  user_email TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'api',
  model_ref TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sessions_tenant_user ON sessions(tenant_id, user_email, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS channel_allowlist (
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  channel TEXT NOT NULL,
  external_subject TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'paired',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, channel, external_subject)
);
