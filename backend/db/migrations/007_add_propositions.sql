-- Migration: Add propositions table
-- Description: Stores atomic facts extracted from chunks for fine-grained reasoning.

CREATE TABLE IF NOT EXISTS propositions (
    id UUID PRIMARY KEY,
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (now() AT TIME ZONE 'utc'),
    
    -- Metadata about the proposition
    is_atomic BOOLEAN DEFAULT TRUE,
    
    CONSTRAINT fk_note FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
    CONSTRAINT fk_chunk FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
);

-- Index for retrieving propositions by chunk (context expansion)
CREATE INDEX IF NOT EXISTS idx_propositions_chunk_id ON propositions(chunk_id);

-- Index for retrieving propositions by note
CREATE INDEX IF NOT EXISTS idx_propositions_note_id ON propositions(note_id);
