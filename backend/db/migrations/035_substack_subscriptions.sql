-- Migration 035: Native Substack / RSS publication subscriptions and feed reading articles
-- Syncs Substack RSS feeds, matches essays against the user's Neo4j concepts (prioritizing shaky ones),
-- and surfaces first-class Substack Reading Cards in /api/feed.

CREATE TABLE IF NOT EXISTS substack_subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feed_url VARCHAR(2048) NOT NULL,
    site_url VARCHAR(2048) NOT NULL,
    title VARCHAR(300) NOT NULL,
    author VARCHAR(200),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_substack_sub_user_feed UNIQUE (user_id, feed_url)
);

CREATE INDEX IF NOT EXISTS idx_substack_subs_user ON substack_subscriptions(user_id, active);

CREATE TABLE IF NOT EXISTS substack_feed_articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subscription_id UUID NOT NULL REFERENCES substack_subscriptions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    article_url VARCHAR(2048) NOT NULL,
    dedupe_key CHAR(64) NOT NULL,
    publication_name VARCHAR(300) NOT NULL,
    author VARCHAR(200),
    title VARCHAR(500) NOT NULL,
    summary TEXT NOT NULL,
    excerpt_markdown TEXT NOT NULL DEFAULT '',
    published_at TIMESTAMP WITH TIME ZONE,
    matched_concepts JSONB NOT NULL DEFAULT '[]'::jsonb,
    relevance_score DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    ingested_note_id UUID,
    dismissed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_substack_article_user_dedupe UNIQUE (user_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_substack_articles_user_feed
    ON substack_feed_articles(user_id, dismissed_at, relevance_score DESC, published_at DESC);
