-- Migration 025: LeetCode-style problems and attempts for pattern/pseudocode/mistake recall.
CREATE TABLE IF NOT EXISTS coding_problems (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    url TEXT,
    difficulty TEXT CHECK (difficulty IN ('easy', 'medium', 'hard')),
    pattern TEXT,
    key_insight TEXT,
    pseudocode TEXT,
    solution TEXT,
    language TEXT,
    complexity TEXT,
    concept_id VARCHAR(255),
    pattern_concept_id VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_coding_problems_user_title ON coding_problems (user_id, lower(title));

CREATE TABLE IF NOT EXISTS coding_attempts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem_id UUID NOT NULL REFERENCES coding_problems(id) ON DELETE CASCADE,
    outcome TEXT NOT NULL CHECK (outcome IN ('solved', 'hint', 'failed')),
    mistake TEXT,
    mistake_tag TEXT,
    minutes INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_coding_attempts_problem ON coding_attempts (problem_id, created_at DESC);
