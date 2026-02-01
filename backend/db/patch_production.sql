-- RUN THIS IN SUPABASE SQL EDITOR

-- 1. Fix User Schema (Resolves 500 Error on Login)
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255) UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITH TIME ZONE;

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);

-- 2. Fix Notes Schema (Resolves Vector Init Error)
-- Ensure vector extension is enabled
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding column with correct dimensions for Gemini (3072)
ALTER TABLE notes ADD COLUMN IF NOT EXISTS embedding vector(3072);
