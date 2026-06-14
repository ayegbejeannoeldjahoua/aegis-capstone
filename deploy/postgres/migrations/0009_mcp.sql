-- v1.22 BR-MCP-01/02/03: private vetted MCP gateway.
-- Servers must arrive with a signed manifest, pass injection scan, and be
-- approved via the existing dual-control queue before any tool becomes
-- callable. Each tool is namespaced server_id/tool_id so the same tool name
-- across two servers cannot shadow.

BEGIN;

CREATE TABLE IF NOT EXISTS mcp_servers (
  server_id        TEXT PRIMARY KEY,
  display_name     TEXT NOT NULL,
  version          TEXT NOT NULL,
  manifest_hash    TEXT NOT NULL,                 -- sha256 of canonical tools
  public_key       TEXT NOT NULL,                 -- base64 ed25519
  status           TEXT NOT NULL DEFAULT 'pending_approval'
                     CHECK (status IN ('pending_approval','approved','quarantined','removed')),
  command          TEXT,
  args             JSONB DEFAULT '[]'::jsonb,
  env              JSONB DEFAULT '{}'::jsonb,
  cwd              TEXT,
  notes            TEXT,
  registered_by    TEXT NOT NULL,
  approved_by      TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mcp_tools (
  server_id    TEXT NOT NULL REFERENCES mcp_servers(server_id) ON DELETE CASCADE,
  tool_id      TEXT NOT NULL,
  description  TEXT NOT NULL DEFAULT '',
  parameters   JSONB NOT NULL DEFAULT '{}'::jsonb,
  pii_class    TEXT NOT NULL DEFAULT 'med',
  egress       TEXT,
  scan_action  TEXT NOT NULL DEFAULT 'allow' CHECK (scan_action IN ('allow','alert','deny')),
  PRIMARY KEY (server_id, tool_id)
);

CREATE INDEX IF NOT EXISTS idx_mcp_tools_tool_id ON mcp_tools(tool_id);
CREATE INDEX IF NOT EXISTS idx_mcp_servers_status ON mcp_servers(status);

COMMIT;
