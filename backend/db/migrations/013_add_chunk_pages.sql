-- Migration 013: Add page range metadata to chunks

ALTER TABLE chunks
ADD COLUMN IF NOT EXISTS page_start INTEGER,
ADD COLUMN IF NOT EXISTS page_end INTEGER;
