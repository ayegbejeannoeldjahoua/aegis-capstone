-- 0011: operational dashboard metrics.
--
-- Audit payloads are encrypted by design, so the dashboard keeps a narrow
-- plaintext metrics ledger for non-sensitive operational counters and timings.
-- It intentionally stores no prompts, answers, retrieved document bodies, or
-- secrets.

CREATE TABLE IF NOT EXISTS dashboard_chat_metrics (
  trace_id                    TEXT PRIMARY KEY,
  tenant_id                   TEXT NOT NULL,
  subject                     TEXT NOT NULL,
  role_id                     TEXT,
  skill_id                    TEXT,
  status                      TEXT NOT NULL DEFAULT 'success',
  error_type                  TEXT,
  refusal_reason              TEXT,
  started_at                  TIMESTAMPTZ NOT NULL,
  ended_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
  e2e_latency_ms              DOUBLE PRECISION,
  tokens_total                INTEGER NOT NULL DEFAULT 0,
  prompt_tokens               INTEGER NOT NULL DEFAULT 0,
  completion_tokens           INTEGER NOT NULL DEFAULT 0,
  estimated_cost_usd          NUMERIC(14, 6),
  cost_instrumented           BOOLEAN NOT NULL DEFAULT FALSE,
  policy_decision_count       INTEGER NOT NULL DEFAULT 0,
  policy_allow_count          INTEGER NOT NULL DEFAULT 0,
  policy_deny_count           INTEGER NOT NULL DEFAULT 0,
  retrieval_calls             INTEGER NOT NULL DEFAULT 0,
  retrieved_docs              INTEGER NOT NULL DEFAULT 0,
  zero_result_retrievals      INTEGER NOT NULL DEFAULT 0,
  pii_redactions_applied      INTEGER NOT NULL DEFAULT 0,
  prompt_injection_findings   INTEGER NOT NULL DEFAULT 0,
  cross_tenant_leakage_alerts INTEGER NOT NULL DEFAULT 0,
  budget_refusal              BOOLEAN NOT NULL DEFAULT FALSE,
  model_provider_errors       INTEGER NOT NULL DEFAULT 0,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dashboard_chat_metrics_tenant_started
  ON dashboard_chat_metrics(tenant_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_dashboard_chat_metrics_started
  ON dashboard_chat_metrics(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_dashboard_chat_metrics_status
  ON dashboard_chat_metrics(status, started_at DESC);

CREATE TABLE IF NOT EXISTS dashboard_stage_metrics (
  id          BIGSERIAL PRIMARY KEY,
  trace_id    TEXT NOT NULL,
  tenant_id   TEXT NOT NULL,
  stage       TEXT NOT NULL,
  duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
  metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dashboard_stage_metrics_tenant_stage_time
  ON dashboard_stage_metrics(tenant_id, stage, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dashboard_stage_metrics_trace
  ON dashboard_stage_metrics(trace_id);
