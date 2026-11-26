-- What grounded an assistant answer: the concepts it used and a short retrieval summary
-- (intent, documents and concepts retrieved). Lets a reopened conversation show the same
-- "concepts involved" context the live answer showed.
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS meta_json JSONB;
