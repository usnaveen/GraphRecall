-- Migration 031: code-sandbox runs are evidence (tests passed on the phone).
ALTER TABLE knowledge_evidence DROP CONSTRAINT IF EXISTS knowledge_evidence_kind_check;
ALTER TABLE knowledge_evidence ADD CONSTRAINT knowledge_evidence_kind_check
    CHECK (kind IN ('review', 'quiz', 'territory', 'note', 'self_rating', 'course', 'project', 'leetcode',
                    'resume', 'agent', 'sandbox'));
