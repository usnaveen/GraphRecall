-- Migration 020: Denormalize user_id onto chunks, sync via trigger, and upgrade
-- chunk embeddings to pgvector HNSW (replacing legacy ivfflat lists=100).

ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS user_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_chunks_user'
    ) THEN
        ALTER TABLE chunks
            ADD CONSTRAINT fk_chunks_user
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;
END
$$;

UPDATE chunks AS c
SET user_id = n.user_id
FROM notes AS n
WHERE c.note_id = n.id
  AND (c.user_id IS NULL OR c.user_id <> n.user_id);

ALTER TABLE chunks
    ALTER COLUMN user_id SET NOT NULL;

CREATE OR REPLACE FUNCTION chunks_sync_user_id()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.user_id IS NULL OR (TG_OP = 'UPDATE' AND NEW.note_id IS DISTINCT FROM OLD.note_id) THEN
        SELECT n.user_id INTO NEW.user_id
        FROM notes AS n
        WHERE n.id = NEW.note_id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_chunks_sync_user_id ON chunks;
CREATE TRIGGER trg_chunks_sync_user_id
BEFORE INSERT OR UPDATE OF note_id ON chunks
FOR EACH ROW
EXECUTE FUNCTION chunks_sync_user_id();

CREATE INDEX IF NOT EXISTS idx_chunks_user_level
    ON chunks (user_id, chunk_level);

DROP INDEX IF EXISTS idx_chunks_embedding;

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE embedding IS NOT NULL;
