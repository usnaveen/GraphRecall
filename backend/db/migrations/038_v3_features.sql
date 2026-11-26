-- Migration 038: GraphRecall v3 features (domain taxonomy cache, unified ingested_resources, overnight job telemetry)

CREATE TABLE IF NOT EXISTS domain_taxonomy_map (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    raw_domain TEXT NOT NULL,
    subject TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, raw_domain)
);

CREATE TABLE IF NOT EXISTS ingested_resources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('email_newsletter', 'link', 'rss', 'youtube', 'note')),
    source_url TEXT,
    dedupe_key CHAR(64) NOT NULL,
    sender TEXT,
    publication_name TEXT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    excerpt_markdown TEXT NOT NULL DEFAULT '',
    matched_concepts JSONB NOT NULL DEFAULT '[]'::jsonb,
    relevance_score DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    digest_status TEXT NOT NULL DEFAULT 'pending',
    published_at TIMESTAMPTZ,
    dismissed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ingested_resources_user_dedupe UNIQUE (user_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_ingested_resources_user_feed
    ON ingested_resources (user_id, dismissed_at, digest_status, relevance_score DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS overnight_job_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_date DATE NOT NULL,
    job_kind TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    items_processed INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_overnight_job_runs_user_date
    ON overnight_job_runs (user_id, run_date DESC, started_at DESC);
