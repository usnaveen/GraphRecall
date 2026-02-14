-- Migration 014: Fix embedding dimension from 768 to 3072
-- Gemini embedding-001 produces 3072-dimensional vectors, not 768.
-- This migration fixes the chunks table to match the actual embedding model.

-- Drop the old ivfflat index (it's tied to the old dimension)
DROP INDEX IF EXISTS idx_chunks_embedding;

-- Alter the column type to the correct dimension
-- NOTE: This will fail if there are existing 768-dim embeddings stored.
-- In that case, truncate chunks first: TRUNCATE chunks CASCADE;
ALTER TABLE chunks
ALTER COLUMN embedding TYPE vector(3072);

-- Recreate the ivfflat index with correct dimension
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
