-- Migration 019: Generated tsvector + GIN index on child chunks for chunk-level hybrid RRF retrieval.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(content, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv
    ON chunks USING GIN (content_tsv)
    WHERE chunk_level = 'child';
