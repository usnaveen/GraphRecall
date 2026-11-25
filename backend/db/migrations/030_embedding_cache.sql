-- Migration 030: content-addressed embedding cache, per user.
-- key = sha256(model | dims | text). Re-ingesting or retrying a document reuses vectors already
-- paid for. Scoped to the owner (no cross-user sharing, so no "someone embedded this text" signal)
-- and deleted with the account.
CREATE TABLE IF NOT EXISTS embedding_cache (
    key TEXT NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dims INTEGER NOT NULL,
    embedding REAL[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, key)
);
