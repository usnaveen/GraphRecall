-- Migration 016: Store explicit 1-4 FSRS ratings on study_sessions for history replay & calibration
-- Mapping: 1 = again ("No idea"), 2 = hard ("Shaky"), 3 = good ("Knew it"), 4 = easy ("Easy")
ALTER TABLE study_sessions
ADD COLUMN IF NOT EXISTS rating SMALLINT CHECK (rating BETWEEN 1 AND 4);

CREATE INDEX IF NOT EXISTS idx_study_sessions_user_concept_time
  ON study_sessions (user_id, concept_id, reviewed_at DESC);
