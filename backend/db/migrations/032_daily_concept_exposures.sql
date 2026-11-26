-- 032_daily_concept_exposures.sql
-- Tracks which concepts were shown and graded per user per UTC day so the ADHD-friendly
-- feed enforces a bounded daily working-memory concept budget instead of overwhelming
-- the learner with dozens of unrelated concepts at once.

CREATE TABLE IF NOT EXISTS daily_concept_exposures (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exposure_date DATE NOT NULL DEFAULT CURRENT_DATE,
    concept_id VARCHAR(255) NOT NULL,
    concept_name TEXT,
    domain VARCHAR(255),
    shown_count INT NOT NULL DEFAULT 1,
    graded_count INT NOT NULL DEFAULT 0,
    last_difficulty VARCHAR(20),
    first_shown_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_shown_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, exposure_date, concept_id)
);

CREATE INDEX IF NOT EXISTS idx_daily_concept_exposures_user_date
    ON daily_concept_exposures (user_id, exposure_date);
