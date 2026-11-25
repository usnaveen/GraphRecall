-- Migration 029: agents (MCP) can queue "show me this later" items; label them as such.
ALTER TABLE later_items DROP CONSTRAINT IF EXISTS later_items_source_check;
ALTER TABLE later_items ADD CONSTRAINT later_items_source_check
    CHECK (source IN ('typed', 'voice', 'share', 'chat', 'agent'));
