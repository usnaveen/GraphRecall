-- Migration 014: Standardize embedding dimension to 768
-- gemini-embedding-001 supports MRL (Matryoshka Representation Learning).
-- 768 dims = 99.74% quality of 3072, 75% less storage, faster vector ops.
-- This migration handles both old 3072-dim and wrong 768-dim schemas.

-- Drop the old ivfflat index (it's tied to the old dimension)
DROP INDEX IF EXISTS idx_chunks_embedding;

-- Alter the column type to 768 dimensions
-- NOTE: This will fail if there are existing embeddings of a different dimension.
-- In that case, truncate chunks first: TRUNCATE chunks CASCADE;
ALTER TABLE chunks
ALTER COLUMN embedding TYPE vector(768);

-- Also fix notes embedding column if it was set to 3072
ALTER TABLE notes
ALTER COLUMN embedding TYPE vector(768);

-- Recreate the ivfflat index with correct dimension
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
