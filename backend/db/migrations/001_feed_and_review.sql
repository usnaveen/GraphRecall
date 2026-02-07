-- Migration 001: Add tables for feed, review sessions, and user uploads
-- Run this after initial schema setup

-- Add SM-2 columns to proficiency_scores if not exist
ALTER TABLE proficiency_scores 
ADD COLUMN IF NOT EXISTS easiness_factor DECIMAL(4,2) DEFAULT 2.5,
ADD COLUMN IF NOT EXISTS interval_days INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS repetition_count INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS next_review TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
ADD COLUMN IF NOT EXISTS total_reviews INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS correct_streak INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- Concept review sessions (for human-in-the-loop)
CREATE TABLE IF NOT EXISTS concept_review_sessions (
    id VARCHAR(255) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note_id UUID REFERENCES notes(id) ON DELETE SET NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    concepts_json TEXT NOT NULL,  -- JSON blob of ConceptReviewSession
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    
    CONSTRAINT valid_review_status CHECK (status IN ('pending', 'approved', 'cancelled', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_review_sessions_user ON concept_review_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_review_sessions_status ON concept_review_sessions(status);
CREATE INDEX IF NOT EXISTS idx_review_sessions_expires ON concept_review_sessions(expires_at);

-- User uploads (screenshots, infographics)
CREATE TABLE IF NOT EXISTS user_uploads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    upload_type VARCHAR(50) NOT NULL DEFAULT 'screenshot',
    file_url TEXT NOT NULL,
    thumbnail_url TEXT,
    title VARCHAR(255),
    description TEXT,
    linked_concepts VARCHAR(255)[] DEFAULT '{}',  -- Array of concept IDs
    ocr_text TEXT,  -- Extracted text from image (future feature)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_shown_at TIMESTAMP WITH TIME ZONE,
    show_count INTEGER DEFAULT 0,
    
    CONSTRAINT valid_upload_type CHECK (upload_type IN ('screenshot', 'infographic', 'diagram'))
);

CREATE INDEX IF NOT EXISTS idx_uploads_user ON user_uploads(user_id);
CREATE INDEX IF NOT EXISTS idx_uploads_type ON user_uploads(upload_type);
CREATE INDEX IF NOT EXISTS idx_uploads_created ON user_uploads(created_at DESC);

-- Update study_sessions for feed tracking
ALTER TABLE study_sessions 
ADD COLUMN IF NOT EXISTS concept_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS item_type VARCHAR(50),
ADD COLUMN IF NOT EXISTS interaction_type VARCHAR(50),
ADD COLUMN IF NOT EXISTS is_correct BOOLEAN,
ADD COLUMN IF NOT EXISTS response_time_ms INTEGER,
ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- Chat conversations (for GraphRAG assistant)
CREATE TABLE IF NOT EXISTS chat_conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,  -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    sources_json JSONB,  -- Referenced notes/concepts
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT valid_role CHECK (role IN ('user', 'assistant', 'system'))
);

CREATE INDEX IF NOT EXISTS idx_conversations_user ON chat_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON chat_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON chat_messages(created_at);

-- Generated content cache (MCQs, flashcards)
CREATE TABLE IF NOT EXISTS generated_content (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    concept_id VARCHAR(255) NOT NULL,
    content_type VARCHAR(50) NOT NULL,  -- 'mcq', 'fill_blank', 'flashcard', 'mermaid'
    content_json JSONB NOT NULL,
    quality_score DECIMAL(3,2),  -- User rating
    times_used INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT valid_content_type CHECK (content_type IN ('mcq', 'fill_blank', 'flashcard', 'mermaid', 'showcase'))
);

CREATE INDEX IF NOT EXISTS idx_generated_user_concept ON generated_content(user_id, concept_id);
CREATE INDEX IF NOT EXISTS idx_generated_type ON generated_content(content_type);

-- User daily stats (for streaks and heatmap)
CREATE TABLE IF NOT EXISTS daily_stats (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stat_date DATE NOT NULL,
    reviews_completed INTEGER DEFAULT 0,
    concepts_learned INTEGER DEFAULT 0,
    notes_added INTEGER DEFAULT 0,
    accuracy DECIMAL(3,2),
    time_spent_seconds INTEGER DEFAULT 0,
    
    UNIQUE(user_id, stat_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_stats_user_date ON daily_stats(user_id, stat_date DESC);

-- Add embedding column alias for consistency
-- Idempotent check: Only rename if 'embedding_vector' exists
DO $$
BEGIN
  -- Safe rename only if target doesn't exist
  IF EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='notes' AND column_name='embedding_vector') THEN
    IF NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='notes' AND column_name='embedding') THEN
        ALTER TABLE notes RENAME COLUMN embedding_vector TO embedding;
    END IF;
  END IF;

  -- Ensure title column exists (fix for legacy schema)
  IF NOT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='notes' AND column_name='title') THEN
    ALTER TABLE notes ADD COLUMN title VARCHAR(500);
  END IF;
END $$;

-- Update notes embedding index
DROP INDEX IF EXISTS idx_notes_embedding;
CREATE INDEX IF NOT EXISTS idx_notes_embedding ON notes 
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
