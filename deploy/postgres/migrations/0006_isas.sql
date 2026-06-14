-- 0006: ISA (Ideal State Artifact) — a per-task record of the agent's "definition of done."
-- One row per chat trace; iscs is the list of atomic, binary Ideal-State Criteria with their
-- post-run verification outcome (satisfied + evidence). Read by the chat response and by the
-- Audit tab; isa.verify and isc.verify audit events fire alongside, sharing the same trace_id.
CREATE TABLE IF NOT EXISTS isas (
  trace_id    TEXT PRIMARY KEY,
  tenant_id   TEXT NOT NULL,
  subject     TEXT NOT NULL,
  goal        TEXT NOT NULL,
  iscs        JSONB NOT NULL DEFAULT '[]'::jsonb,
  verified    BOOLEAN NOT NULL DEFAULT FALSE,
  total       INT NOT NULL DEFAULT 0,
  met         INT NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_isas_tenant_time ON isas(tenant_id, created_at DESC);
