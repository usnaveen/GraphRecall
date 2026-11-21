"""Offline unit tests for SM-2, FSRS, slider mapping, and review session persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.models.feed_schemas import DifficultyLevel, ReviewResult
from backend.services.spaced_repetition import (
    FSRSAlgorithm,
    FSRS_GRADE_TO_INTERACTION_TYPE,
    FSRS_GRADE_TO_SLIDER_LABEL,
    IOS_SLIDER_BAND_TO_DIFFICULTY,
    SpacedRepetitionService,
    difficulty_to_fsrs_grade,
)


class _FakePgClient:
    """Minimal in-memory fake Postgres client capturing SQL queries and params."""

    def __init__(self, rows=None, fail_on_rating_insert: bool = False):
        self.rows = rows or []
        self.fail_on_rating_insert = fail_on_rating_insert
        self.inserts: list[tuple[str, dict]] = []
        self.updates: list[tuple[str, dict]] = []

    async def execute_query(self, query: str, params: dict | None = None):
        return self.rows

    async def execute_insert(self, query: str, params: dict | None = None):
        if self.fail_on_rating_insert and "rating" in query:
            raise RuntimeError("column 'rating' of relation 'study_sessions' does not exist")
        self.inserts.append((query, params or {}))
        return "inserted-id"

    async def execute_update(self, query: str, params: dict | None = None):
        self.updates.append((query, params or {}))
        return 1


def test_ios_slider_band_to_fsrs_grade_mapping():
    expected = [
        ("Easy", DifficultyLevel.EASY, 4, "review:easy"),
        ("Knew it", DifficultyLevel.GOOD, 3, "review:good"),
        ("Shaky", DifficultyLevel.HARD, 2, "review:hard"),
        ("No idea", DifficultyLevel.AGAIN, 1, "review:again"),
    ]
    for label, diff_enum, grade, interaction in expected:
        assert IOS_SLIDER_BAND_TO_DIFFICULTY[label] == diff_enum
        assert difficulty_to_fsrs_grade(label) == grade
        assert difficulty_to_fsrs_grade(diff_enum) == grade
        assert difficulty_to_fsrs_grade(diff_enum.value) == grade
        assert FSRS_GRADE_TO_SLIDER_LABEL[grade] == label
        assert FSRS_GRADE_TO_INTERACTION_TYPE[grade] == interaction


def test_fsrs_lapse_stability_cannot_increase():
    """Regression test: small S + low R lapse must reduce or cap stability <= old S."""
    old_s = 0.4
    new_s = FSRSAlgorithm.next_stability(s=old_s, d=5.0, r=0.2, grade=1)
    assert 0.1 <= new_s <= old_s
    assert FSRSAlgorithm.retrievability(-3.0, 2.0) == 1.0


def test_fsrs_cold_start_priors_monotonic_with_complexity():
    easy_s, easy_d = FSRSAlgorithm.cold_start_priors(complexity_score=2.0)
    hard_s, hard_d = FSRSAlgorithm.cold_start_priors(complexity_score=9.0)
    assert hard_d > easy_d
    assert 0.4 <= hard_s < easy_s <= 2.6

    overdue_score = FSRSAlgorithm.calculate_priority_score(
        stability=2.0, difficulty=5.0, elapsed_days=20.0, reps=2
    )
    cliff_score = FSRSAlgorithm.calculate_priority_score(
        stability=5.0, difficulty=5.0, elapsed_days=11.0, reps=2
    )
    fresh_score = FSRSAlgorithm.calculate_priority_score(
        stability=10.0, difficulty=5.0, elapsed_days=0.5, reps=2
    )
    assert overdue_score > cliff_score > fresh_score


@pytest.mark.asyncio
async def test_record_review_logs_interaction_type_and_rating_with_fallback():
    now = datetime.now(timezone.utc)
    pg_row = [
        {
            "item_id": "concept-1",
            "user_id": "user-1",
            "easiness_factor": 2.5,
            "interval_days": 3,
            "repetition_count": 1,
            "last_review": now - timedelta(days=3),
            "next_review": now,
            "total_reviews": 1,
            "correct_streak": 1,
            "stability": 3.0,
            "difficulty_fsrs": 5.0,
            "reps_fsrs": 1,
        }
    ]
    pg = _FakePgClient(rows=pg_row, fail_on_rating_insert=False)
    sr = SpacedRepetitionService(pg, algorithm="fsrs")

    await sr.record_review(
        ReviewResult(
            item_id="concept-1",
            item_type="mcq",
            user_id="user-1",
            difficulty=DifficultyLevel.HARD,
            response_time_ms=4200,
        )
    )
    assert len(pg.updates) == 1
    assert len(pg.inserts) == 1
    query, params = pg.inserts[0]
    assert "interaction_type" in query
    assert "rating" in query
    assert params["interaction_type"] == "review:hard"
    assert params["rating"] == 2
    assert params["response_time_ms"] == 4200

    # Verify clean fallback when migration 016 (`rating` column) is not yet applied
    pg_legacy = _FakePgClient(rows=pg_row, fail_on_rating_insert=True)
    sr_legacy = SpacedRepetitionService(pg_legacy, algorithm="fsrs")
    await sr_legacy.record_review(
        ReviewResult(
            item_id="concept-1",
            item_type="mcq",
            user_id="user-1",
            difficulty=DifficultyLevel.AGAIN,
        )
    )
    assert len(pg_legacy.inserts) == 1
    fallback_query, fallback_params = pg_legacy.inserts[0]
    assert "rating" not in fallback_params
    assert fallback_params["interaction_type"] == "review:again"
    assert "interaction_type" in fallback_query


@pytest.mark.asyncio
async def test_get_due_items_ranks_by_fsrs_retrievability_when_fsrs_enabled():
    now = datetime.now(timezone.utc)
    rows = [
        {
            "item_id": "fresh-concept",
            "item_type": "concept",
            "easiness_factor": 2.5,
            "interval": 1,
            "repetition": 1,
            "last_review": now - timedelta(hours=6),
            "next_review": now - timedelta(hours=1),
            "total_reviews": 2,
            "correct_streak": 2,
            "mastery_score": 0.6,
            "stability": 12.0,
            "difficulty_fsrs": 4.0,
            "reps_fsrs": 2,
        },
        {
            "item_id": "forgetting-concept",
            "item_type": "concept",
            "easiness_factor": 2.5,
            "interval": 1,
            "repetition": 1,
            "last_review": now - timedelta(days=10),
            "next_review": now - timedelta(hours=1),
            "total_reviews": 2,
            "correct_streak": 0,
            "mastery_score": 0.4,
            "stability": 1.5,
            "difficulty_fsrs": 6.5,
            "reps_fsrs": 2,
        },
    ]
    pg = _FakePgClient(rows=rows)
    sr = SpacedRepetitionService(pg, algorithm="fsrs")
    due = await sr.get_due_items("user-1", limit=10)

    assert len(due) == 2
    assert due[0]["sm2_data"]["item_id"] == "forgetting-concept"
    assert due[0]["fsrs_data"]["retrievability"] < due[1]["fsrs_data"]["retrievability"]
    assert due[0]["priority_score"] > due[1]["priority_score"]
