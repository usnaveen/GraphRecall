-- Migration 026: Agent bridge (external always-on agent <-> GraphRecall)
-- See docs/agent-bridge/PROPOSAL.md.
--
-- Tables:
--   agent_api_keys       scoped, per-user API keys (only a SHA-256 hash is stored)
--   agent_feed_items     agent-curated feed cards (pending -> approved/rejected)
--   agent_daily_digests  one curated digest per user per day
--   agent_requests       "ask my agent" queue (app -> external agent -> app)
--
-- Applied once by backend/db/migrate.py (recorded in schema_migrations). Every statement still
-- uses IF NOT EXISTS, so databases that ran the bridge's earlier 015_agent_bridge.sql are fine.

CREATE TABLE IF NOT EXISTS agent_api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL DEFAULT 'agent',
    key_prefix VARCHAR(32) NOT NULL UNIQUE,      -- public, shown in UI ("grk_ab12cd34")
    key_hash CHAR(64) NOT NULL UNIQUE,           -- sha256(pepper + full key), hex
    scopes TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_agent_api_keys_user ON agent_api_keys(user_id);

CREATE TABLE IF NOT EXISTS agent_feed_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_id UUID REFERENCES agent_api_keys(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    item_kind VARCHAR(30) NOT NULL DEFAULT 'article',
    title VARCHAR(500) NOT NULL,
    summary TEXT NOT NULL,                       -- curated summary only, never raw email bodies
    body_json JSONB NOT NULL DEFAULT '{}'::jsonb, -- optional card payload (flashcard/mcq)
    source_url VARCHAR(2048),
    source_kind VARCHAR(30) NOT NULL DEFAULT 'web',
    reason TEXT NOT NULL,                        -- why the agent picked this for the user
    concept_ids TEXT[] NOT NULL DEFAULT '{}',    -- Neo4j Concept.id values (same user)
    target_date DATE NOT NULL,
    dedupe_key CHAR(64) NOT NULL,                -- sha256(normalized source_url) or sha256(content)
    idempotency_key VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT valid_agent_feed_status CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    CONSTRAINT valid_agent_feed_kind CHECK (item_kind IN ('article', 'flashcard', 'mcq', 'exam_prep', 'note')),
    CONSTRAINT valid_agent_source_kind CHECK (source_kind IN ('email', 'substack', 'web', 'exam', 'calendar', 'other')),
    CONSTRAINT uq_agent_feed_dedupe UNIQUE (user_id, dedupe_key, target_date)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_feed_idempotency
    ON agent_feed_items(user_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_feed_user_date
    ON agent_feed_items(user_id, target_date, status);

CREATE TABLE IF NOT EXISTS agent_daily_digests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_id UUID REFERENCES agent_api_keys(id) ON DELETE SET NULL,
    digest_date DATE NOT NULL,
    title VARCHAR(500) NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    item_ids UUID[] NOT NULL DEFAULT '{}',
    focus_concept_ids TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_agent_digest_day UNIQUE (user_id, digest_date)
);

CREATE TABLE IF NOT EXISTS agent_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id UUID,                        -- optional chat_conversations.id
    question TEXT NOT NULL,
    context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    claimed_by_key_id UUID REFERENCES agent_api_keys(id) ON DELETE SET NULL,
    claim_token UUID,
    lease_expires_at TIMESTAMP WITH TIME ZONE,
    attempts INTEGER NOT NULL DEFAULT 0,
    answer_text TEXT,
    answer_json JSONB,                           -- citations / structured extras
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    claimed_at TIMESTAMP WITH TIME ZONE,
    answered_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT valid_agent_request_status CHECK (
        status IN ('queued', 'claimed', 'answered', 'failed', 'cancelled', 'expired')
    )
);

CREATE INDEX IF NOT EXISTS idx_agent_requests_user_status
    ON agent_requests(user_id, status, created_at);
