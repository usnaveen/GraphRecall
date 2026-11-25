-- Migration 027: Agent bridge audit log + shared rate-limit counters
-- Applied once by backend/db/migrate.py; idempotent (IF NOT EXISTS) like 026_agent_bridge.sql.

-- Who did what through the bridge. Metadata only: tool names, ids and counts, never
-- card text, answers, questions or knowledge content.
CREATE TABLE IF NOT EXISTS agent_audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_id UUID REFERENCES agent_api_keys(id) ON DELETE SET NULL,
    actor VARCHAR(10) NOT NULL,                 -- 'agent' or 'user'
    action VARCHAR(50) NOT NULL,                -- tool_call, key_created, feed_item_approved
    tool VARCHAR(64),
    target_id UUID,
    details JSONB NOT NULL DEFAULT '{}'::jsonb, -- counts only
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_agent_audit_actor CHECK (actor IN ('agent', 'user'))
);

CREATE INDEX IF NOT EXISTS idx_agent_audit_user_time ON agent_audit_log(user_id, created_at DESC);

-- Fixed-window counters for PostgresRateLimiter (shared across workers).
CREATE TABLE IF NOT EXISTS agent_rate_limits (
    bucket VARCHAR(200) NOT NULL,
    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket, window_start)
);
