-- Migration 039: MCP Tasks for the agent bridge (io.modelcontextprotocol/tasks, 2026-07-28).
--
-- A long-running bridge tool (ingest_link, save_learning_session) answers at once with a task id
-- and runs in the background. The row is written before the answer is sent, so tasks/get on any
-- later connection finds it. Ids are unguessable (secrets.token_urlsafe) and every read is bound
-- to the owning user. Results are kept until expires_at (longest run + 24 h).

CREATE TABLE IF NOT EXISTS agent_tasks (
    id VARCHAR(64) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_id UUID REFERENCES agent_api_keys(id) ON DELETE SET NULL,
    tool VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'working',   -- working | completed | failed | cancelled
    status_message TEXT,
    result JSONB,                                    -- the tools/call result, when completed
    error JSONB,                                     -- the JSON-RPC error, when failed
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_user_status ON agent_tasks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_expires ON agent_tasks(expires_at);
