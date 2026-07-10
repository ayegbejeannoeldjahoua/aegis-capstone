-- 0013: durable per-user chat history.
--
-- Chat history is stored separately from the encrypted audit ledger so the UI
-- can recall conversations while audit remains the authoritative governance
-- evidence. Rows are scoped by tenant and user email, and carry month_key for
-- current-month views plus recent monthly history.

CREATE TABLE IF NOT EXISTS chat_conversations (
  id              UUID PRIMARY KEY,
  tenant_id       TEXT NOT NULL,
  user_email      TEXT NOT NULL,
  title           TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_message_at TIMESTAMPTZ,
  month_key       TEXT NOT NULL,
  archived        BOOLEAN NOT NULL DEFAULT FALSE,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id              UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
  tenant_id       TEXT NOT NULL,
  user_email      TEXT NOT NULL,
  role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content         TEXT NOT NULL,
  trace_id        TEXT,
  provider        TEXT,
  model           TEXT,
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  total_tokens    INTEGER,
  token_source    TEXT NOT NULL DEFAULT 'unmetered',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  month_key       TEXT NOT NULL,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_chat_conversations_user_month
  ON chat_conversations(tenant_id, user_email, month_key, updated_at DESC)
  WHERE archived = FALSE;

CREATE INDEX IF NOT EXISTS idx_chat_conversations_last_message
  ON chat_conversations(tenant_id, user_email, last_message_at DESC)
  WHERE archived = FALSE;

CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_time
  ON chat_messages(conversation_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_chat_messages_trace
  ON chat_messages(trace_id)
  WHERE trace_id IS NOT NULL;
