-- Migration 010: Backfill legacy review columns into current schema

DO $$
BEGIN
  -- Backfill next_review_due from legacy next_review if it exists
  IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_name = 'proficiency_scores' AND column_name = 'next_review'
    )
    AND EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_name = 'proficiency_scores' AND column_name = 'next_review_due'
    )
  THEN
    UPDATE proficiency_scores
    SET next_review_due = COALESCE(next_review_due, next_review)
    WHERE next_review_due IS NULL AND next_review IS NOT NULL;
  END IF;

  -- Backfill last_reviewed from legacy last_review if it exists
  IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_name = 'proficiency_scores' AND column_name = 'last_review'
    )
    AND EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_name = 'proficiency_scores' AND column_name = 'last_reviewed'
    )
  THEN
    UPDATE proficiency_scores
    SET last_reviewed = COALESCE(last_reviewed, last_review)
    WHERE last_reviewed IS NULL AND last_review IS NOT NULL;
  END IF;
END $$;
