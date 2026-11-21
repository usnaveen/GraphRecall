-- The column patches that used to run in main.py's lifespan on every start. They run before
-- init.sql (version 000b_init) because init.sql creates indexes on these columns, which fails on a
-- database created before the columns existed. IF EXISTS makes them no-ops on a fresh database,
-- where init.sql then creates the tables with the columns already in place.

ALTER TABLE IF EXISTS notes ADD COLUMN IF NOT EXISTS resource_type VARCHAR(50) DEFAULT 'notes';
ALTER TABLE IF EXISTS notes ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE IF EXISTS notes ADD COLUMN IF NOT EXISTS summary TEXT;

ALTER TABLE IF EXISTS proficiency_scores ADD COLUMN IF NOT EXISTS easiness_factor DECIMAL(3,2) DEFAULT 2.5;
ALTER TABLE IF EXISTS proficiency_scores ADD COLUMN IF NOT EXISTS interval_days INTEGER DEFAULT 1;
ALTER TABLE IF EXISTS proficiency_scores ADD COLUMN IF NOT EXISTS repetition_count INTEGER DEFAULT 0;
ALTER TABLE IF EXISTS proficiency_scores ADD COLUMN IF NOT EXISTS total_reviews INTEGER DEFAULT 0;
ALTER TABLE IF EXISTS proficiency_scores ADD COLUMN IF NOT EXISTS correct_streak INTEGER DEFAULT 0;
ALTER TABLE IF EXISTS proficiency_scores ADD COLUMN IF NOT EXISTS next_review_due TIMESTAMP WITH TIME ZONE;
