-- Per-user daily usage of the expensive (LLM-backed) actions, for quotas (backend/services/quota.py).
CREATE TABLE IF NOT EXISTS usage_daily (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    kind VARCHAR(32) NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, kind)
);
