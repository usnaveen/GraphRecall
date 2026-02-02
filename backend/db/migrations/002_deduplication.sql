-- Migration: Add content_hash for deduplication
-- Created: 2026-02-02

-- Add SHA-256 hash column to notes table
ALTER TABLE notes ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_notes_hash ON notes(user_id, content_hash);

-- Optional: Backfill existing notes (this is a best-effort for existing data)
-- In a real prod scenario we might want a script, but valid SQL is complex without pgrypto
-- We will leave existing ones null (they won't block new duplicates, which is fine)
