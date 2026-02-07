-- Migration 008: Add FSRS (Free Spaced Repetition Scheduler) columns
-- FSRS uses Stability (S), Difficulty (D), and Retrievability (R) parameters
-- instead of SM-2's Easiness Factor.

ALTER TABLE proficiency_scores
ADD COLUMN IF NOT EXISTS stability FLOAT DEFAULT NULL,
ADD COLUMN IF NOT EXISTS difficulty_fsrs FLOAT DEFAULT NULL,
ADD COLUMN IF NOT EXISTS reps_fsrs INTEGER DEFAULT 0;
