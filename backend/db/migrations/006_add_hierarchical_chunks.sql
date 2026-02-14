-- Migration 006: Add hierarchical chunks table
-- Enables semantic chunking with Parent/Child support

CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    parent_chunk_id UUID REFERENCES chunks(id) ON DELETE SET NULL,
    chunk_index INTEGER,
    
    content TEXT NOT NULL,
    chunk_level VARCHAR(20),  -- 'parent', 'child'
    source_location JSONB,    -- {"page": 1, "slide": 5, "section": "..."}
    
    -- Embeddings (Child chunks only usually)
    embedding vector(3072),  -- Gemini embedding-001 produces 3072 dimensions
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chunks_note ON chunks(note_id);
CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(parent_chunk_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Table for tracking citation usage in RAG
CREATE TABLE IF NOT EXISTS rag_citations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    response_id UUID NOT NULL,
    chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    citation_rank INTEGER,
    similarity_score DECIMAL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rag_citations_response ON rag_citations(response_id);
