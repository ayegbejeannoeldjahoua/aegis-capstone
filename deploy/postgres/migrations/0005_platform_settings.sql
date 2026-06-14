-- Platform-wide key/value settings (single global knobs, distinct from per-tenant governance).
-- First use: `default_model` = the model the platform admin selects to serve everyone.
CREATE TABLE IF NOT EXISTS platform_settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_by TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
