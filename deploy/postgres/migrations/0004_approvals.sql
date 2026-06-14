-- 0004: dual-control approval workflow. High-risk actions queue here and must be
-- approved by a DIFFERENT principal (two-person rule) before they execute.
CREATE TABLE IF NOT EXISTS pending_actions (
  id          BIGSERIAL PRIMARY KEY,
  tenant_id   TEXT NOT NULL,
  action      TEXT NOT NULL,
  resource    JSONB NOT NULL DEFAULT '{}'::jsonb,
  reason      TEXT,
  status      TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | executed | expired
  requester   TEXT NOT NULL,
  approver    TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at  TIMESTAMPTZ,
  executed_at TIMESTAMPTZ,
  expires_at  TIMESTAMPTZ NOT NULL DEFAULT now() + interval '24 hours'
);
CREATE INDEX IF NOT EXISTS idx_pending_actions_tenant_status ON pending_actions(tenant_id, status);
