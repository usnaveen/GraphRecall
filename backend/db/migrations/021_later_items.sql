-- Migration 021: "show me this later" captures. A thought, link or dictated note that should come
-- back in the feed at a chosen time instead of being studied now.
CREATE TABLE IF NOT EXISTS later_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    url TEXT,
    source TEXT NOT NULL DEFAULT 'typed' CHECK (source IN ('typed', 'voice', 'share', 'chat')),
    when_phrase TEXT,
    show_at TIMESTAMPTZ NOT NULL,
    shown_at TIMESTAMPTZ,
    done_at TIMESTAMPTZ,
    note_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_later_items_due
    ON later_items (user_id, show_at)
    WHERE done_at IS NULL;
