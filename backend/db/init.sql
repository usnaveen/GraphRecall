-- GraphRecall PostgreSQL Schema Initialization
-- This file runs automatically when the PostgreSQL container starts
-- CONSOLIDATED: Includes all tables from migrations for clean deploys

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    google_id VARCHAR(255) UNIQUE,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    profile_picture TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP WITH TIME ZONE,
    settings_json JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);

-- Notes table (source of truth for all content)
CREATE TABLE IF NOT EXISTS notes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500),
    content_type VARCHAR(50) NOT NULL DEFAULT 'markdown',
    content_text TEXT NOT NULL,
    content_hash VARCHAR(64),  -- SHA-256 hash for deduplication
    source_url VARCHAR(2048),
    resource_type VARCHAR(50) NOT NULL DEFAULT 'notes',
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    embedding vector(768),  -- Gemini embedding-001 with MRL (768 dims optimal)

    CONSTRAINT valid_content_type CHECK (content_type IN ('text', 'markdown', 'pdf', 'handwriting')),
    CONSTRAINT valid_resource_type CHECK (resource_type IN ('notes', 'lecture_slides', 'youtube', 'article', 'chat_conversation', 'documentation', 'research', 'book'))
);

-- Hierarchical chunks table (parent/child chunking for RAG)
CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    parent_chunk_id UUID REFERENCES chunks(id) ON DELETE SET NULL,
    chunk_index INTEGER,

    content TEXT NOT NULL,
    chunk_level VARCHAR(20),  -- 'parent', 'child'
    source_location JSONB,    -- {"page": 1, "slide": 5, "section": "..."}

    -- Embeddings (child chunks only, gemini-embedding-001 MRL @ 768 dims)
    embedding vector(768),

    -- Image metadata (BookChunker)
    images JSONB DEFAULT '[]',

    -- Page range metadata
    page_start INTEGER,
    page_end INTEGER,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chunks_note ON chunks(note_id);
CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(parent_chunk_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- RAG citations (tracking which chunks are used in responses)
CREATE TABLE IF NOT EXISTS rag_citations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    response_id UUID NOT NULL,
    chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    citation_rank INTEGER,
    similarity_score DECIMAL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_citations_response ON rag_citations(response_id);

-- Propositions (atomic facts extracted from chunks)
CREATE TABLE IF NOT EXISTS propositions (
    id UUID PRIMARY KEY,
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    is_atomic BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_propositions_chunk_id ON propositions(chunk_id);
CREATE INDEX IF NOT EXISTS idx_propositions_note_id ON propositions(note_id);

-- Proficiency scores (tracking user knowledge per concept)
CREATE TABLE IF NOT EXISTS proficiency_scores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    concept_id VARCHAR(255) NOT NULL,  -- References Neo4j Concept.id
    score DECIMAL(3,2) NOT NULL DEFAULT 0.10 CHECK (score >= 0.0 AND score <= 1.0),
    last_reviewed TIMESTAMP WITH TIME ZONE,
    next_review_due TIMESTAMP WITH TIME ZONE,
    streak_count INTEGER DEFAULT 0,
    difficulty_rating DECIMAL(3,2) DEFAULT 0.50,
    -- FSRS (Free Spaced Repetition Scheduler) columns
    stability FLOAT DEFAULT NULL,
    difficulty_fsrs FLOAT DEFAULT NULL,
    reps_fsrs INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(user_id, concept_id)
);

-- Flashcards (generated study materials)
CREATE TABLE IF NOT EXISTS flashcards (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    concept_id VARCHAR(255) NOT NULL,
    front_content TEXT NOT NULL,
    back_content TEXT NOT NULL,
    difficulty DECIMAL(3,2) DEFAULT 0.50,
    source_note_ids UUID[] DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    times_reviewed INTEGER DEFAULT 0,
    times_correct INTEGER DEFAULT 0,
    is_liked BOOLEAN DEFAULT FALSE,
    is_saved BOOLEAN DEFAULT FALSE
);

-- Quizzes (generated questions)
CREATE TABLE IF NOT EXISTS quizzes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    concept_id VARCHAR(255) NOT NULL,
    question_text TEXT NOT NULL,
    question_type VARCHAR(50) NOT NULL DEFAULT 'mcq',
    options_json JSONB,
    correct_answer TEXT NOT NULL,
    explanation TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_question_type CHECK (question_type IN ('mcq', 'open_ended', 'code')),
    is_liked BOOLEAN DEFAULT FALSE,
    is_saved BOOLEAN DEFAULT FALSE
);

-- Study sessions (tracking learning activity)
CREATE TABLE IF NOT EXISTS study_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_type VARCHAR(50) NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP WITH TIME ZONE,
    concepts_covered VARCHAR(255)[] DEFAULT '{}',
    performance_summary JSONB,

    CONSTRAINT valid_session_type CHECK (session_type IN ('quiz', 'flashcard', 'teaching'))
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_notes_user_id ON notes(user_id);
CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_resource_type ON notes(resource_type);
CREATE INDEX IF NOT EXISTS idx_notes_hash ON notes(user_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_proficiency_user_concept ON proficiency_scores(user_id, concept_id);
CREATE INDEX IF NOT EXISTS idx_proficiency_next_review ON proficiency_scores(next_review_due);
CREATE INDEX IF NOT EXISTS idx_flashcards_user_concept ON flashcards(user_id, concept_id);
CREATE INDEX IF NOT EXISTS idx_quizzes_user_concept ON quizzes(user_id, concept_id);
CREATE INDEX IF NOT EXISTS idx_study_sessions_user ON study_sessions(user_id);

-- Chat conversations table
CREATE TABLE IF NOT EXISTS chat_conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) DEFAULT 'New Chat',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_saved_to_knowledge BOOLEAN DEFAULT FALSE,
    summary TEXT
);

-- Communities (graph clustering)
CREATE TABLE IF NOT EXISTS communities (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    level INTEGER DEFAULT 0,
    parent_id UUID,
    size INTEGER DEFAULT 0,
    summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS community_nodes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    community_id UUID NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    concept_id VARCHAR(255) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_communities_user ON communities(user_id);
CREATE INDEX IF NOT EXISTS idx_community_nodes_user ON community_nodes(user_id);
CREATE INDEX IF NOT EXISTS idx_community_nodes_concept ON community_nodes(concept_id);

-- Chat messages table
CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    sources_json JSONB DEFAULT '[]',
    is_saved_for_quiz BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Saved responses for quiz generation
CREATE TABLE IF NOT EXISTS saved_responses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id UUID REFERENCES chat_messages(id) ON DELETE SET NULL,
    topic VARCHAR(255),
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Chat indexes
CREATE INDEX IF NOT EXISTS idx_chat_conversations_user ON chat_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_conversations_updated ON chat_conversations(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation ON chat_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_saved_responses_user ON saved_responses(user_id);

-- Vector similarity index for semantic search on notes
CREATE INDEX IF NOT EXISTS idx_notes_embedding ON notes
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Insert a default test user for development
INSERT INTO users (id, email)
VALUES ('00000000-0000-0000-0000-000000000001', 'test@graphrecall.dev')
ON CONFLICT (email) DO NOTHING;
