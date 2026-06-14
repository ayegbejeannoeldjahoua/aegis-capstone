-- 0003: semantic memory. The original embedding column was vector(384) and unused.
-- Recreate at the embedding model's dimension (768 for nomic-embed-text) and index it
-- for cosine similarity. Empty column, so the drop/recreate is safe.
ALTER TABLE memories DROP COLUMN IF EXISTS embedding;
ALTER TABLE memories ADD COLUMN embedding vector(768);
CREATE INDEX IF NOT EXISTS idx_memories_embedding ON memories USING hnsw (embedding vector_cosine_ops);
