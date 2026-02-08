-- Migration 012: Add summary field to communities

ALTER TABLE communities
ADD COLUMN IF NOT EXISTS summary TEXT;
