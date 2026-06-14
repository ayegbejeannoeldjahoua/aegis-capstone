-- v1.21 PAI slice 3: satisfaction / learning capture.
-- Records a binary thumb (1=up, -1=down) plus optional free-text note per
-- assistant turn, keyed on the audit trace_id so the feedback is anchored to
-- the exact governed action that produced the output.
--
-- Low-rated turns are surfaced in the Audit tab as a learning-loop signal
-- (the human review queue), and aggregated per skill_id for the per-skill
-- VERIFY trend line.

BEGIN;

CREATE TABLE IF NOT EXISTS turn_feedback (
  id           BIGSERIAL PRIMARY KEY,
  trace_id     TEXT NOT NULL,                 -- audit_events.trace_id anchor
  tenant_id    TEXT NOT NULL,                 -- tenant of the rater (RLS-scoped)
  principal    TEXT NOT NULL,                 -- email/sub who rated
  skill_id     TEXT,                          -- the skill that produced the turn
  rating       SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
  note         TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_turn_feedback_tenant_rating ON turn_feedback(tenant_id, rating, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_turn_feedback_trace ON turn_feedback(trace_id);
CREATE INDEX IF NOT EXISTS idx_turn_feedback_skill ON turn_feedback(skill_id, rating);

-- Same RLS pattern as v1.20: tenant isolation enforced at DB layer.
ALTER TABLE turn_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE turn_feedback FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_turn_feedback ON turn_feedback;
CREATE POLICY tenant_isolation_turn_feedback ON turn_feedback
  USING      (current_setting('app.tenant_id', true) IN (tenant_id, '*'))
  WITH CHECK (current_setting('app.tenant_id', true) IN (tenant_id, '*'));

COMMIT;
