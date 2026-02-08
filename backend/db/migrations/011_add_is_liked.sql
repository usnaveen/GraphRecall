-- Migration 011: Add is_liked column to flashcards and quizzes tables
-- Required for the like toggle feature in the feed

-- Add is_liked column to flashcards if it doesn't exist
ALTER TABLE flashcards 
ADD COLUMN IF NOT EXISTS is_liked BOOLEAN DEFAULT FALSE;

-- Add is_liked column to quizzes if it doesn't exist
ALTER TABLE quizzes 
ADD COLUMN IF NOT EXISTS is_liked BOOLEAN DEFAULT FALSE;
