-- Migration 015: Always-On Agent durable job queue, proactive insights, and run telemetry
-- Created: 2026-11-21

CREATE TABLE IF NOT EXISTS agent_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_type VARCHAR(64) NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    run_after TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked_at TIMESTAMP WITH TIME ZONE,
    locked_by VARCHAR(128),
    last_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_agent_job_status CHECK (status IN ('pending', 'running', 'completed', 'dead_letter'))
);

CREATE INDEX IF NOT EXISTS idx_agent_jobs_claimable
    ON agent_jobs (run_after, created_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_agent_jobs_user
    ON agent_jobs (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_insights (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    insight_type VARCHAR(64) NOT NULL,
    title VARCHAR(500) NOT NULL,
    body_md TEXT NOT NULL,
    concept_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_quotes JSONB NOT NULL DEFAULT '[]'::jsonb,
    action_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT valid_agent_insight_type CHECK (insight_type IN ('connection', 'conflict', 'remedial', 'briefing')),
    CONSTRAINT valid_agent_insight_status CHECK (status IN ('active', 'dismissed', 'acted'))
);

CREATE INDEX IF NOT EXISTS idx_agent_insights_user_status
    ON agent_insights (user_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trigger_type VARCHAR(64) NOT NULL,
    job_id UUID REFERENCES agent_jobs(id) ON DELETE SET NULL,
    thread_id VARCHAR(255),
    model VARCHAR(128),
    tool_calls_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    status VARCHAR(32) NOT NULL,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT valid_agent_run_status CHECK (status IN ('completed', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_user
    ON agent_runs (user_id, created_at DESC);
