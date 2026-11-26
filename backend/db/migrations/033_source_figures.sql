-- Figures cropped from the user's own source PDFs (scripts/extract_figures.py).
--
-- The image bytes live here, not in object storage: book figures are copyrighted, so they must
-- never sit behind a public bucket URL. They are served only to their owner by
-- GET /api/figures/{id}, and they go when the note (or the account) goes.
CREATE TABLE IF NOT EXISTS source_figures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    label TEXT NOT NULL,              -- "Figure 3.1"
    caption TEXT NOT NULL,            -- caption text without the label
    mime TEXT NOT NULL DEFAULT 'image/png',
    image BYTEA NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (note_id, page, label)
);

CREATE INDEX IF NOT EXISTS idx_source_figures_user ON source_figures (user_id);
