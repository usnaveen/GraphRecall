-- Migration 007: Expand Feed Item Types
-- Add support for code_challenge, term_card, and diversify question_type constraints

ALTER TABLE quizzes DROP CONSTRAINT IF EXISTS valid_question_type;
ALTER TABLE quizzes ADD CONSTRAINT valid_question_type 
    CHECK (question_type IN ('mcq', 'open_ended', 'code', 'fill_blank', 'code_challenge', 'term_card', 'diagram', 'infographic'));

-- Add language column to quizzes for code_challenge
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS language VARCHAR(50);
ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS initial_code TEXT;

-- Update generated_content constraints
ALTER TABLE generated_content DROP CONSTRAINT IF EXISTS valid_content_type;
ALTER TABLE generated_content ADD CONSTRAINT valid_content_type 
    CHECK (content_type IN ('mcq', 'fill_blank', 'flashcard', 'mermaid', 'showcase', 'code_challenge', 'term_card'));
