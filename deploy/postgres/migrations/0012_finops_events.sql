-- 0012: durable FinOps budget-governance event ledger.
--
-- dashboard_chat_metrics keeps aggregate-safe operational counters. finops_events
-- records one compact, non-sensitive FinOps decision per governed chat turn so
-- request counts, budget checks, model routing, and unmetered provider activity
-- remain visible even when a model provider does not return token/cost usage.

CREATE TABLE IF NOT EXISTS finops_events (
  id                       BIGSERIAL PRIMARY KEY,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  trace_id                 TEXT NOT NULL,
  request_id               TEXT,
  tenant_id                TEXT NOT NULL,
  user_email               TEXT,
  team_id                  TEXT,
  role                     TEXT,
  action                   TEXT NOT NULL DEFAULT 'chat.turn',
  decision                 TEXT NOT NULL,
  provider                 TEXT,
  model                    TEXT,
  input_tokens             INTEGER,
  output_tokens            INTEGER,
  total_tokens             INTEGER,
  token_source             TEXT NOT NULL DEFAULT 'unmetered',
  estimated_cost_usd       NUMERIC(14, 6),
  budget_limit_usd         NUMERIC(14, 6),
  budget_remaining_usd     NUMERIC(14, 6),
  budget_limit_tokens      INTEGER,
  budget_remaining_tokens  INTEGER,
  budget_profile           JSONB NOT NULL DEFAULT '{}'::jsonb,
  reason                   TEXT,
  reached_model            BOOLEAN NOT NULL DEFAULT FALSE,
  blocked_before_model     BOOLEAN NOT NULL DEFAULT FALSE,
  status                   TEXT NOT NULL,
  metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE finops_events ADD COLUMN IF NOT EXISTS team_id TEXT;
ALTER TABLE finops_events ADD COLUMN IF NOT EXISTS token_source TEXT NOT NULL DEFAULT 'unmetered';

CREATE UNIQUE INDEX IF NOT EXISTS idx_finops_events_trace_action
  ON finops_events(trace_id, action);

CREATE INDEX IF NOT EXISTS idx_finops_events_tenant_time
  ON finops_events(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_finops_events_team_time
  ON finops_events(team_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_finops_events_status_time
  ON finops_events(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_finops_events_provider_model_time
  ON finops_events(provider, model, created_at DESC);
