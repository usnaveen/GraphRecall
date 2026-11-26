"""A concept imported moments ago has a placeholder score row (score 0.10, every other column NULL).
Its first grade must load default scheduling data instead of failing validation."""

from backend.services.spaced_repetition import SpacedRepetitionService


class _PG:
    async def execute_query(self, query, params=None):
        return [{"item_id": "c1", "user_id": "u", "easiness_factor": None, "interval_days": None,
                 "repetition_count": None, "last_review": None, "next_review": None,
                 "total_reviews": None, "correct_streak": None, "stability": None,
                 "difficulty_fsrs": None, "reps_fsrs": None}]


async def test_placeholder_row_loads_defaults():
    svc = SpacedRepetitionService(_PG())
    data = await svc.get_or_create_sm2_data(user_id="u", item_id="c1", item_type="flashcard")
    assert data.easiness_factor == 2.5 and data.interval == 1 and data.repetition == 0
    assert data.total_reviews == 0 and data.next_review is not None
