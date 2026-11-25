-- Migration 023: log every chat routing decision so a small intent classifier can be trained and audited.
-- One row per analysed chat message. `source` says who decided: the LLM, the trained model, or the
-- trained model in shadow mode (LLM decided, model's guess recorded alongside for comparison).
CREATE TABLE IF NOT EXISTS intent_decisions (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    intent TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('llm', 'model', 'fallback', 'greeting')),
    model_intent TEXT,
    model_confidence REAL,
    model_version TEXT,
    llm_intent TEXT,
    entities JSONB NOT NULL DEFAULT '[]'::jsonb,
    latency_ms REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_intent_decisions_user_created
    ON intent_decisions (user_id, created_at DESC);
