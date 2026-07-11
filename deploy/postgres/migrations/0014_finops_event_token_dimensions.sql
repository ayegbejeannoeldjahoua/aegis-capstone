-- 0014: additive FinOps token analytics dimensions.
--
-- Some environments may have already applied 0012 before team_id and
-- token_source were added. Keep this as a separate migration so deployed
-- databases receive the columns instead of relying on edits to an applied file.

ALTER TABLE finops_events ADD COLUMN IF NOT EXISTS team_id TEXT;
ALTER TABLE finops_events ADD COLUMN IF NOT EXISTS token_source TEXT NOT NULL DEFAULT 'unmetered';

CREATE INDEX IF NOT EXISTS idx_finops_events_team_time
  ON finops_events(team_id, created_at DESC);
