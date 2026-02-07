-- Migration 009: Add image metadata to chunks

ALTER TABLE chunks
ADD COLUMN IF NOT EXISTS images JSONB DEFAULT '[]';

-- Ensure existing NULL values become empty arrays for consistency
UPDATE chunks SET images = '[]' WHERE images IS NULL;

-- Optional: small GIN index for querying images by filename/page if needed later
-- CREATE INDEX IF NOT EXISTS idx_chunks_images_gin ON chunks USING gin (images);
