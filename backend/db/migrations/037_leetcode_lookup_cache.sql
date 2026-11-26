-- Migration 037: LeetCode public lookup cache + problem number/tags on coding_problems.
CREATE TABLE IF NOT EXISTS leetcode_catalog (
    number INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    url TEXT NOT NULL,
    difficulty TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    tags TEXT[] NOT NULL DEFAULT '{}',
    paid_only BOOLEAN NOT NULL DEFAULT FALSE,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE coding_problems ADD COLUMN IF NOT EXISTS number INTEGER;
ALTER TABLE coding_problems ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';
CREATE UNIQUE INDEX IF NOT EXISTS uq_coding_problems_user_number
    ON coding_problems (user_id, number)
    WHERE number IS NOT NULL;
