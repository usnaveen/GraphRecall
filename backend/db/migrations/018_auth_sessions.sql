-- Sign in with Apple and GraphRecall-issued sessions (backend/auth/sessions.py, backend/auth/apple.py).

-- Apple users are keyed on Apple's stable `sub`. Apple may withhold the email (the user can decline
-- the scope), so email becomes optional (UNIQUE still holds for the ones we have).
ALTER TABLE users ADD COLUMN IF NOT EXISTS apple_id VARCHAR(255) UNIQUE;
ALTER TABLE users ALTER COLUMN email DROP NOT NULL;
-- Apple refresh token from the authorization-code exchange, encrypted (Fernet). Only used to revoke
-- the user's Apple authorization when they delete their account (App Store guideline 5.1.1(v)).
ALTER TABLE users ADD COLUMN IF NOT EXISTS apple_refresh_token_enc TEXT;

-- Refresh tokens: only a SHA-256 hash is stored. Rotated on every use, and `family_id` ties a chain of
-- rotations together so reuse of an old token can revoke the whole chain.
CREATE TABLE IF NOT EXISTS auth_refresh_tokens (
    token_hash CHAR(64) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_auth_refresh_user ON auth_refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_refresh_family ON auth_refresh_tokens(family_id);

-- Server-issued, single-use nonces for Sign in with Apple (replay protection).
CREATE TABLE IF NOT EXISTS auth_nonces (
    nonce_hash CHAR(64) PRIMARY KEY,
    expires_at TIMESTAMPTZ NOT NULL
);
