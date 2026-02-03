-- Web Search Caching
CREATE TABLE IF NOT EXISTS web_search_cache (
    query_hash VARCHAR(64) PRIMARY KEY,
    query_text TEXT NOT NULL,
    results_json JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_web_cache_created ON web_search_cache(created_at);

-- Lazy Quiz Generation Candidates
CREATE TABLE IF NOT EXISTS quiz_candidates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_note_id UUID REFERENCES notes(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    topic VARCHAR(255),
    difficulty DECIMAL(3,2) DEFAULT 0.50,
    status VARCHAR(50) DEFAULT 'pending', -- pending, generated, ignored
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_quiz_candidates_user ON quiz_candidates(user_id);
CREATE INDEX IF NOT EXISTS idx_quiz_candidates_topic ON quiz_candidates(topic);
CREATE INDEX IF NOT EXISTS idx_quiz_candidates_status ON quiz_candidates(status);
