-- Migration: Add source column for tracking content provenance
-- Created: 2026-02-02

-- Add source column to quizzes table
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'generated';

-- Add source column to flashcards table
ALTER TABLE flashcards ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'generated';

-- Create index for analytics (e.g. how many from web vs generated)
CREATE INDEX IF NOT EXISTS idx_quizzes_source ON quizzes(source);
