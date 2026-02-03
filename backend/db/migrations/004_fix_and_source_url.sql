-- Migration: Fix chat schema and add source_url
-- Created: 2026-02-03

-- 1. Fix missing column in chat_conversations (for existing DBs)
ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS is_saved_to_knowledge BOOLEAN DEFAULT FALSE;
ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS summary TEXT;

-- 2. Add source_url to quizzes/flashcards for Web Augmentation transparency
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE flashcards ADD COLUMN IF NOT EXISTS source_url TEXT;

-- 3. Ensure we have the source column (from 003, but safe to repeat IF NOT EXISTS logic if needed, though we assume 003 ran)
-- (No action needed if 003 ran, but just in case)
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'generated';
