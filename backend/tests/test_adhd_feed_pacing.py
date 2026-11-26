"""Offline unit tests for ADHD-friendly daily concept tracking and anti-overwhelm pacing."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from backend.models.feed_schemas import FeedFilterRequest, FeedItem, FeedItemType
from backend.services.feed_service import FeedService
from backend.feed_ranker import NullGraphSignals
from backend.services.feed_pacing import (
    DailyConceptEntry,
    DailyConceptLedger,
    InMemoryDailyExposureStore,
    cap_cards_per_concept,
    get_memory_exposure_store,
    load_daily_concept_ledger,
    record_daily_concept_review,
    record_feed_impressions,
    select_daily_focus_concepts,
)


def _make_concept(
    idx: int,
    *,
    domain: str = "ML",
    priority: float = 1.0,
    related: list[str] | None = None,
) -> dict[str, Any]:
    cid = f"c-{idx:02d}"
    return {
        "id": cid,
        "name": f"Concept {idx:02d}",
        "definition": f"Definition for concept {idx:02d}. Second sentence gives key detail.",
        "domain": domain,
        "complexity_score": 5,
        "priority_score": priority,
        "related_concepts": related or [],
        "prerequisites": [],
        "sm2_data": {
            "item_id": cid,
            "priority_score": priority,
            "correct_streak": 1,
        },
        "fsrs_data": {
            "stability": 3.0,
            "difficulty": 5.0,
            "reps": 1,
            "elapsed_days": 4.0,
        },
    }


def test_select_daily_focus_concepts_caps_thirty_backlog_to_seven() -> None:
    due = [_make_concept(i, priority=30 - i) for i in range(1, 31)]
    ledger = DailyConceptLedger(
        user_id="u-test-1",
        exposure_date=datetime(2026, 11, 26, tzinfo=timezone.utc).date(),
        daily_concept_cap=7,
    )

    focused = select_daily_focus_concepts(due, ledger)

    assert len(focused) == 7
    assert len({c["id"] for c in focused}) == 7
    assert focused[0]["id"] == "c-01"


def test_select_daily_focus_concepts_continues_unconsolidated_today_before_new_topics() -> None:
    due = [_make_concept(i, priority=20 - i) for i in range(1, 21)]
    store = InMemoryDailyExposureStore()
    now = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)

    async def scenario() -> None:
        # Morning session showed 5 concepts; 2 were graded Easy (consolidated), 3 are still shaky/ungraded.
        store.record_impressions(
            "u-test-2",
            now.date(),
            [
                ("c-10", "Concept 10", "ML"),
                ("c-11", "Concept 11", "ML"),
                ("c-12", "Concept 12", "ML"),
                ("c-13", "Concept 13", "ML"),
                ("c-14", "Concept 14", "ML"),
            ],
        )
        await record_daily_concept_review(
            None, "u-test-2", "c-10", "easy", now=now, memory_store=store
        )
        await record_daily_concept_review(
            None, "u-test-2", "c-11", "easy", now=now, memory_store=store
        )
        await record_daily_concept_review(
            None, "u-test-2", "c-12", "again", now=now, memory_store=store
        )

        ledger = await load_daily_concept_ledger(
            None, "u-test-2", daily_concept_cap=7, now=now, memory_store=store
        )
        # 5 already shown today -> only 2 new concepts allowed today (total distinct today <= 7)
        focused = select_daily_focus_concepts(due, ledger)
        focused_ids = [c["id"] for c in focused]

        # Must retain the 3 unconsolidated concepts from earlier today
        assert {"c-12", "c-13", "c-14"}.issubset(set(focused_ids))
        # Must NOT re-nag the 2 concepts already graded Easy today
        assert "c-10" not in focused_ids
        assert "c-11" not in focused_ids
        # At most 2 brand-new concepts added so total distinct concepts shown today == 7
        new_ids = [cid for cid in focused_ids if cid not in {"c-12", "c-13", "c-14"}]
        assert len(new_ids) == 2
        assert len(set(ledger.shown_concept_ids) | set(focused_ids)) == 7

    asyncio.run(scenario())


def test_select_daily_focus_concepts_prefers_graph_connected_cluster() -> None:
    # Seed c-01 is highest priority; c-08 and c-09 are direct graph neighbors of c-01 with slightly
    # lower raw urgency than unrelated c-02 ("Cooking"), over a realistic priority range [0.40, 1.00].
    c1 = _make_concept(1, domain="Transformers", priority=1.00, related=["Concept 08", "Concept 09"])
    c2 = _make_concept(2, domain="Cooking", priority=0.90)
    c8 = _make_concept(8, domain="Transformers", priority=0.86, related=["Concept 01"])
    c9 = _make_concept(9, domain="Transformers", priority=0.84, related=["Concept 01"])
    c5 = _make_concept(5, domain="Finance", priority=0.40)
    ledger = DailyConceptLedger(
        user_id="u-test-cluster",
        exposure_date=datetime(2026, 11, 26, tzinfo=timezone.utc).date(),
        daily_concept_cap=3,
    )

    focused = select_daily_focus_concepts([c1, c2, c8, c9, c5], ledger)
    assert [c["id"] for c in focused] == ["c-01", "c-08", "c-09"]


def test_stretch_unlock_opens_two_more_when_all_seven_consolidated() -> None:
    due = [_make_concept(i, priority=20 - i) for i in range(1, 15)]
    ledger = DailyConceptLedger(
        user_id="u-test-stretch",
        exposure_date=datetime(2026, 11, 26, tzinfo=timezone.utc).date(),
        daily_concept_cap=7,
    )
    for i in range(1, 8):
        cid = f"c-{i:02d}"
        ledger.entries[cid] = DailyConceptEntry(
            concept_id=cid,
            shown_count=1,
            graded_count=1,
            last_difficulty="easy",
        )

    assert ledger.effective_cap == 9
    focused = select_daily_focus_concepts(due, ledger)
    assert [c["id"] for c in focused] == ["c-08", "c-09"]


def test_cap_cards_per_concept_prefers_diverse_modalities() -> None:
    items = [
        FeedItem(id="1", item_type=FeedItemType.MCQ, content={}, concept_id="c-01"),
        FeedItem(id="2", item_type=FeedItemType.MCQ, content={}, concept_id="c-01"),
        FeedItem(id="3", item_type=FeedItemType.TERM_CARD, content={}, concept_id="c-01"),
        FeedItem(id="4", item_type=FeedItemType.FILL_BLANK, content={}, concept_id="c-01"),
        FeedItem(id="5", item_type=FeedItemType.MCQ, content={}, concept_id="c-01"),
    ]
    capped = cap_cards_per_concept(items, max_per_concept=3)
    assert len(capped) == 3
    assert {it.item_type for it in capped} == {
        FeedItemType.MCQ,
        FeedItemType.TERM_CARD,
        FeedItemType.FILL_BLANK,
    }


class _FakePG:
    def __init__(self, quizzes: list[dict[str, Any]], flashcards: list[dict[str, Any]]) -> None:
        self._quizzes = quizzes
        self._flashcards = flashcards

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        q = " ".join(query.split()).lower()
        p = params or {}
        if "from quizzes" in q and "concept_id = any(:cids)" in q:
            cids = set(p.get("cids") or [])
            return [row for row in self._quizzes if row["concept_id"] in cids][: int(p.get("lim", 40))]
        if "from flashcards" in q and "concept_id = any(:cids)" in q:
            cids = set(p.get("cids") or [])
            return [row for row in self._flashcards if row["concept_id"] in cids][: int(p.get("lim", 40))]
        return []

    async def execute_update(self, query: str, params: dict[str, Any] | None = None) -> int:
        return 1


class _FakeNeo4j:
    def __init__(self, concepts: list[dict[str, Any]]) -> None:
        self._concepts = concepts

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        q = " ".join(query.split()).lower()
        if "return distinct c.domain" in q:
            domains = sorted({c["domain"] for c in self._concepts if c.get("domain")})
            return [{"domain": d} for d in domains]
        if "where c.id in $concept_ids" in q:
            wanted = set((params or {}).get("concept_ids") or [])
            return [{"c": c} for c in self._concepts if c["id"] in wanted]
        return []


def test_feed_service_enforces_daily_concept_cap_and_spaces_repeats(monkeypatch) -> None:
    monkeypatch.setenv("FEED_DAILY_CONCEPT_CAP", "5")
    monkeypatch.setenv("FEED_DEMO_CARDS", "0")
    get_memory_exposure_store().clear()

    concepts = [_make_concept(i, priority=30 - i) for i in range(1, 26)]
    quizzes = [
        {
            "id": f"q-{c['id']}",
            "question_text": f"What is {c['name']}?",
            "question_type": "mcq",
            "options_json": [{"id": "A", "text": "Correct", "is_correct": True}],
            "correct_answer": "A",
            "explanation": "Exp",
            "concept_id": c["id"],
            "language": None,
            "initial_code": None,
        }
        for c in concepts
    ]
    flashcards = [
        {
            "id": f"f-{c['id']}",
            "front_content": f"Define {c['name']}",
            "back_content": c["definition"],
            "concept_id": c["id"],
        }
        for c in concepts
    ]

    pg = _FakePG(quizzes=quizzes, flashcards=flashcards)
    neo = _FakeNeo4j(concepts=concepts)
    svc = FeedService(pg, neo, graph_signals=NullGraphSignals())

    async def fake_due(user_id: str, limit: int = 20, include_overdue: bool = True):
        return [
            {
                "sm2_data": c["sm2_data"],
                "fsrs_data": c["fsrs_data"],
                "priority_score": c["priority_score"],
            }
            for c in concepts[:limit]
        ]

    async def fake_stats(user_id: str):
        return {"due_today": 25, "overdue": 5, "total_reviews": 10, "average_mastery": 0.7}

    svc.sr_service.get_due_items = fake_due  # type: ignore[method-assign]
    svc.sr_service.get_user_stats = fake_stats  # type: ignore[method-assign]

    async def run() -> None:
        resp = await svc.get_feed(FeedFilterRequest(user_id="u-feed-cap-test", max_items=10))
        distinct_cids = {it.concept_id for it in resp.items if it.concept_id}
        # Even though 25 concepts are due and 10 cards were requested, at most 5 distinct
        # concepts are introduced today (2 modalities each, interleaved by MMR).
        assert len(resp.items) == 10
        assert len(distinct_cids) <= 5
        assert resp.daily_concept_cap == 5
        assert resp.active_concepts_today == len(distinct_cids)
        assert set(resp.concepts_shown_today) == distinct_cids

        # MMR adjacent-concept guard: no two consecutive cards share the same concept_id!
        for a, b in zip(resp.items, resp.items[1:]):
            assert a.concept_id != b.concept_id

    asyncio.run(run())
    get_memory_exposure_store().clear()
