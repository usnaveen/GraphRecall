-- Migration 005: Community detection tables
-- Created: 2026-02-03

CREATE TABLE IF NOT EXISTS communities (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    level INTEGER DEFAULT 0,
    parent_id UUID,
    size INTEGER DEFAULT 0,
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
