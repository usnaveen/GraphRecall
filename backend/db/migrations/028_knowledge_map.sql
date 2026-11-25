-- Migration 028: the knowledge map of a person.
-- Every signal about what the user knows is one row in knowledge_evidence, tied to a graph
-- concept and/or a skill key (normalised name) for skills that are not in the graph yet
-- ("linear algebra" from a resume before any linear-algebra note exists). One resolver,
-- backend/services/knowledge_map.assess(), turns evidence + review state into strong / shaky /
-- seen / unexposed for the resume view, exposure questions and the MCP tools.

CREATE TABLE IF NOT EXISTS knowledge_evidence (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    concept_id VARCHAR(255),
    skill_key TEXT,
    skill_name TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('review', 'quiz', 'territory', 'note', 'self_rating', 'course',
                                       'project', 'leetcode', 'resume', 'agent')),
    signal REAL NOT NULL CHECK (signal >= 0 AND signal <= 1),   -- estimated mastery this evidence implies
    weight REAL NOT NULL DEFAULT 1.0 CHECK (weight > 0),       -- how much to trust it (before decay)
    source_id TEXT,                                            -- course / project / attempt / card id
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (concept_id IS NOT NULL OR skill_key IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_kevidence_user_concept ON knowledge_evidence (user_id, concept_id) WHERE concept_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_kevidence_user_skill ON knowledge_evidence (user_id, skill_key) WHERE skill_key IS NOT NULL;

-- Skills the user claims or was asked about, including ones not in the graph.
CREATE TABLE IF NOT EXISTS user_skills (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_key TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    concept_id VARCHAR(255),
    self_rating SMALLINT CHECK (self_rating BETWEEN 0 AND 4),  -- 0 never, 1 heard of it, 2 basics, 3 used it, 4 strong
    sources TEXT[] NOT NULL DEFAULT '{}',                       -- resume, course, project, agent, user
    asked_at TIMESTAMPTZ,
    rated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, skill_key)
);

CREATE TABLE IF NOT EXISTS user_profile (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    headline TEXT,
    education_status TEXT,      -- e.g. "MTech student", "working professional"
    institution TEXT,
    program TEXT,
    graduation_year SMALLINT,
    goals TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_courses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code TEXT,
    name TEXT NOT NULL,
    term TEXT,
    grade TEXT,
    institution TEXT,
    topics TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_courses_user ON user_courses (user_id);

CREATE TABLE IF NOT EXISTS user_projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    skills TEXT[] NOT NULL DEFAULT '{}',
    started TEXT,
    ended TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_projects_user ON user_projects (user_id);

-- The latest resume. Text has contact lines stripped before storage; it is never exposed over MCP.
CREATE TABLE IF NOT EXISTS user_resumes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_name TEXT,
    text TEXT NOT NULL,
    skills JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{name, key, section}]
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_resumes_user ON user_resumes (user_id, created_at DESC);
