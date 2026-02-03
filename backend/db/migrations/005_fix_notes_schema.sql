-- Add tags and potential missing columns to notes table
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='notes' AND column_name='tags') THEN
        ALTER TABLE notes ADD COLUMN tags VARCHAR(255)[] DEFAULT '{}';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='notes' AND column_name='summary') THEN
        ALTER TABLE notes ADD COLUMN summary TEXT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='notes' AND column_name='content_hash') THEN
        ALTER TABLE notes ADD COLUMN content_hash VARCHAR(64);
    END IF;
END $$;
