"""Offline unit and integration tests for NeuroFeed ranker and FeedService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.feed_ranker import (
    CandidateCard,
    FeedRanker,
    InMemoryGraphSignals,
    RankerConfig,
    mmr_select,
    pool_centered_cosine_matrix,
)
from backend.models.feed_schemas import FeedFilterRequest, FeedItemType
from backend.services.feed_service import FeedService


def _unit_vec(base: np.ndarray, ortho: np.ndarray, target_cos: float) -> list[float]:
    """Construct a unit vector whose cosine similarity with `base` equals `target_cos`."""
    sin_part = float(np.sqrt(max(0.0, 1.0 - target_cos ** 2)))
    v = target_cos * base + sin_part * ortho
    return (v / np.linalg.norm(v)).tolist()


@pytest.mark.asyncio
async def test_fsrs_retrievability_outranks_fresh_concept():
    ranker = FeedRanker()
    candidates = [
        CandidateCard(
            item_id="fresh-1",
            concept_id="c-fresh",
            item_type="mcq",
            domain="ML",
            stability=15.0,
            difficulty_fsrs=4.0,
            reps_fsrs=4,
            elapsed_days=0.5,
            correct_streak=3,
        ),
        CandidateCard(
            item_id="due-1",
            concept_id="c-due",
            item_type="mcq",
            domain="Systems",
            stability=2.0,
            difficulty_fsrs=6.0,
            reps_fsrs=3,
            elapsed_days=14.0,
            correct_streak=1,
        ),
    ]
    ranked = await ranker.rank("user-1", candidates, limit=5)
    assert [r.card.concept_id for r in ranked] == ["c-due", "c-fresh"]
    assert ranked[0].score > ranked[1].score


@pytest.mark.asyncio
async def test_prerequisite_backtracking_after_lapse():
    now = datetime.now(timezone.utc)
    graph = InMemoryGraphSignals(
        prereq_edges={"backprop": [("chain-rule", 0.95), ("linear-alg", 0.6)]},
        stabilities={"chain-rule": 1.1, "linear-alg": 9.5},
    )
    ranker = FeedRanker(graph_signals=graph, config=RankerConfig(invisible_warmup_lead=False))

    # 1. Missing prerequisite detection
    candidates_without_prereq = [
        CandidateCard(
            item_id="item-bp",
            concept_id="backprop",
            item_type="mcq",
            domain="DL",
            stability=1.2,
            difficulty_fsrs=7.0,
            reps_fsrs=3,
            elapsed_days=1.0,
            last_review_grade=1,
            last_reviewed_at=now - timedelta(hours=2),
            correct_streak=0,
        ),
    ]
    missing = await ranker.missing_backtrack_prerequisites("user-1", candidates_without_prereq, now=now)
    assert "chain-rule" in missing
    assert missing[0] == "chain-rule"

    # 2. Once prerequisite card is in pool, it is boosted with prereq_backtrack + Revisit badge
    candidates = candidates_without_prereq + [
        CandidateCard(
            item_id="item-cr",
            concept_id="chain-rule",
            item_type="flashcard",
            domain="Math",
            stability=4.0,
            difficulty_fsrs=4.5,
            reps_fsrs=2,
            elapsed_days=1.0,
            correct_streak=1,
        ),
        CandidateCard(
            item_id="item-other",
            concept_id="svd",
            item_type="mcq",
            domain="Math",
            stability=8.0,
            difficulty_fsrs=5.0,
            reps_fsrs=2,
            elapsed_days=2.0,
            correct_streak=2,
        ),
    ]
    ranked = await ranker.rank("user-1", candidates, limit=5, now=now)
    by_cid = {r.card.concept_id: r for r in ranked}
    assert by_cid["chain-rule"].reason == "prereq_backtrack"
    assert by_cid["chain-rule"].badge == "Revisit"
    assert ranked[0].card.concept_id == "chain-rule"


@pytest.mark.asyncio
async def test_mmr_never_repeats_same_concept_adjacent_and_respects_recent_history():
    candidates = [
        CandidateCard(item_id="q1", concept_id="c-top", item_type="mcq", domain="AI", stability=1.0, reps_fsrs=2, elapsed_days=8.0),
        CandidateCard(item_id="q2", concept_id="c-top", item_type="flashcard", domain="AI", stability=1.0, reps_fsrs=2, elapsed_days=8.0),
        CandidateCard(item_id="q3", concept_id="c-second", item_type="mcq", domain="DB", stability=3.0, reps_fsrs=2, elapsed_days=5.0),
        CandidateCard(item_id="q4", concept_id="c-third", item_type="mcq", domain="Sys", stability=4.0, reps_fsrs=2, elapsed_days=4.0),
    ]
    ranked = await FeedRanker(config=RankerConfig(invisible_warmup_lead=False)).rank(
        "user-1", candidates, limit=4, recent_concept_ids=["c-top"]
    )
    concept_seq = [r.card.concept_id for r in ranked]
    assert concept_seq[0] == "c-second"  # recent history pushes immediate repeat out of slot 0
    for i in range(len(concept_seq) - 1):
        assert concept_seq[i] != concept_seq[i + 1]


def test_pool_centered_cosine_mmr_handles_narrow_high_cosine_band():
    """Reproduces gemini-embedding-001 narrow band [0.84, 0.94]: near-duplicates separate cleanly."""
    dim = 16
    base = np.zeros(dim)
    base[0] = 1.0
    ortho_dup = np.zeros(dim)
    ortho_dup[1] = 1.0
    ortho_unrel = np.zeros(dim)
    ortho_unrel[2] = 1.0
    ortho_other = np.zeros(dim)
    ortho_other[3] = 1.0

    v_anchor = base.tolist()
    v_near_dup = _unit_vec(base, ortho_dup, 0.935)
    v_unrel_a = _unit_vec(base, ortho_unrel, 0.846)
    v_unrel_b = _unit_vec(base, ortho_other, 0.846)

    sims = pool_centered_cosine_matrix(
        [v_anchor, v_near_dup, v_unrel_a, v_unrel_b], use_pool_centered=True
    )
    # Near-duplicate (0.935) stands well above pool median (>3x higher than unrelated pair at 0.846)
    assert sims[(0, 1)] > 0.55
    assert sims[(0, 2)] < 0.20
    assert sims[(0, 1)] > 3.0 * sims[(0, 2)]

    cards = [
        CandidateCard(item_id="anchor", concept_id="matrix-fact", item_type="mcq", domain="D1", embedding=v_anchor),
        CandidateCard(item_id="near-dup", concept_id="svd", item_type="flashcard", domain="D2", embedding=v_near_dup),
        CandidateCard(item_id="unrel-1", concept_id="c4-plants", item_type="flashcard", domain="D3", embedding=v_unrel_a),
    ]
    # Relevance slightly prefers near-dup over unrel-1, yet MMR places unrel-1 before near-dup
    selected = mmr_select(
        cards,
        relevance_scores=[1.0, 0.85, 0.80],
        config=RankerConfig(
            mmr_lambda=0.55,
            embedding_weight=1.0,
            same_domain_weight=0.0,
            same_type_weight=0.0,
            use_pool_centered_cosine=True,
        ),
        limit=3,
    )
    assert selected == [0, 2, 1]


@pytest.mark.asyncio
async def test_revisit_badge_and_invisible_warmup_lead():
    ranker = FeedRanker(config=RankerConfig(invisible_warmup_lead=True))
    candidates = [
        CandidateCard(
            item_id="hard-lapse",
            concept_id="c-hard",
            item_type="mcq",
            domain="DL",
            stability=1.0,
            reps_fsrs=4,
            elapsed_days=8.0,
            last_review_grade=1,
            correct_streak=0,
        ),
        CandidateCard(
            item_id="warm-hook",
            concept_id="c-warm",
            item_type="mcq",
            domain="Systems",
            stability=5.0,
            reps_fsrs=3,
            elapsed_days=10.0,  # R ~ (1 + 10 / 45)^-1 = 0.818 in [0.72, 0.92]
            last_review_grade=3,
            correct_streak=2,
        ),
        CandidateCard(
            item_id="cold-note",
            concept_id="c-cold",
            item_type="showcase",
            domain="NLP",
            stability=None,
            reps_fsrs=0,
            complexity_score=5.0,
        ),
    ]
    ranked = await ranker.rank("user-1", candidates, limit=3)
    # Invisible warmup moves comfortable ZPD card into slot 0 before hard-lapse
    assert ranked[0].card.concept_id == "c-warm"
    by_cid = {r.card.concept_id: r for r in ranked}
    assert by_cid["c-hard"].badge == "Revisit"
    assert by_cid["c-warm"].badge is None
    assert by_cid["c-cold"].badge is None
    assert by_cid["c-cold"].reason == "cold_start"


class _FakeFeedPgClient:
    """Mock Postgres for offline FeedService.get_feed tests."""

    def __init__(self, now: datetime):
        self.now = now
        self.queries: list[str] = []

    async def execute_query(self, query: str, params: dict | None = None):
        self.queries.append(query)
        q_low = query.lower()
        if "from proficiency_scores ps" in q_low:
            return [
                {
                    "item_id": "c-backprop",
                    "item_type": "concept",
                    "easiness_factor": 2.1,
                    "interval": 1,
                    "repetition": 1,
                    "last_review": self.now - timedelta(days=5),
                    "next_review": self.now - timedelta(days=1),
                    "total_reviews": 3,
                    "correct_streak": 0,
                    "mastery_score": 0.3,
                    "stability": 1.2,
                    "difficulty_fsrs": 7.0,
                    "reps_fsrs": 2,
                },
                {
                    "item_id": "c-fresh",
                    "item_type": "concept",
                    "easiness_factor": 2.6,
                    "interval": 10,
                    "repetition": 3,
                    "last_review": self.now - timedelta(hours=12),
                    "next_review": self.now - timedelta(minutes=10),
                    "total_reviews": 4,
                    "correct_streak": 4,
                    "mastery_score": 0.9,
                    "stability": 18.0,
                    "difficulty_fsrs": 3.0,
                    "reps_fsrs": 4,
                },
            ]
        if "from study_sessions" in q_low and "distinct on" in q_low:
            return [
                {
                    "concept_id": "c-backprop",
                    "interaction_type": "review:again",
                    "is_correct": False,
                    "reviewed_at": self.now - timedelta(hours=3),
                }
            ]
        if "from quizzes" in q_low and "count(*)" not in q_low:
            cids = set((params or {}).get("cids") or [])
            rows = []
            if "c-backprop" in cids:
                rows.append(
                    {
                        "id": "quiz-bp-1",
                        "question_text": "What does backpropagation compute?",
                        "question_type": "mcq",
                        "options_json": ["Gradients", "Weights"],
                        "correct_answer": "Gradients",
                        "explanation": "Computes parameter gradients via chain rule.",
                        "concept_id": "c-backprop",
                        "language": None,
                        "initial_code": None,
                    }
                )
            if "c-fresh" in cids:
                rows.append(
                    {
                        "id": "quiz-fresh-1",
                        "question_text": "What is tokenization?",
                        "question_type": "mcq",
                        "options_json": ["Splitting text", "Sorting"],
                        "correct_answer": "Splitting text",
                        "explanation": "Splits raw text into subword units.",
                        "concept_id": "c-fresh",
                        "language": None,
                        "initial_code": None,
                    }
                )
            if "c-chain-rule" in cids:
                rows.append(
                    {
                        "id": "quiz-cr-1",
                        "question_text": "How do you differentiate f(g(x))?",
                        "question_type": "mcq",
                        "options_json": ["f'(g(x)) * g'(x)", "f'(x) + g'(x)"],
                        "correct_answer": "f'(g(x)) * g'(x)",
                        "explanation": "Chain rule for function composition.",
                        "concept_id": "c-chain-rule",
                        "language": None,
                        "initial_code": None,
                    }
                )
            return rows
        if "from flashcards" in q_low:
            return []
        if "from user_uploads" in q_low:
            return []
        if "count(*)" in q_low:
            return [{"cnt": 0, "due_count": 2, "overdue_count": 1, "reviewed_today": 0, "avg_mastery": 0.6, "max_streak": 4}]
        return []


class _FakeFeedNeo4jClient:
    """Mock Neo4j returning Concept metadata for offline FeedService tests."""

    async def execute_query(self, query: str, params: dict | None = None):
        if "distinct c.domain" in query.lower():
            return [{"domain": "Deep Learning"}, {"domain": "Calculus"}, {"domain": "NLP"}]
        ids = set((params or {}).get("concept_ids") or (params or {}).get("ids") or [])
        catalog = {
            "c-backprop": {"id": "c-backprop", "name": "Backpropagation", "domain": "Deep Learning", "complexity_score": 8},
            "c-fresh": {"id": "c-fresh", "name": "Tokenization", "domain": "NLP", "complexity_score": 3},
            "c-chain-rule": {"id": "c-chain-rule", "name": "Chain Rule", "domain": "Calculus", "complexity_score": 5},
        }
        return [{"c": catalog[cid]} for cid in ids if cid in catalog]


@pytest.mark.asyncio
async def test_feed_service_get_feed_offline_neurofeed_backtracks_without_demo_or_llm(monkeypatch):
    monkeypatch.delenv("FEED_DEMO_CARDS", raising=False)
    monkeypatch.delenv("FEED_RANKER_MODE", raising=False)

    now = datetime.now(timezone.utc)
    pg = _FakeFeedPgClient(now)
    neo4j = _FakeFeedNeo4jClient()
    graph = InMemoryGraphSignals(
        prereq_edges={"c-backprop": [("c-chain-rule", 0.9)]},
        stabilities={"c-chain-rule": 1.0},
    )
    service = FeedService(pg, neo4j, sr_algorithm="fsrs", graph_signals=graph)

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("LLM generation should not run when cached items satisfy max_items")

    service.generate_feed_item = _fail_if_called  # type: ignore[method-assign]

    resp = await service.get_feed(
        FeedFilterRequest(user_id="user-1", max_items=3, item_types=[FeedItemType.MCQ])
    )
    ids = [item.id for item in resp.items]
    cids = [item.concept_id for item in resp.items]

    assert not any(cid.startswith("demo-") for cid in cids if cid)
    assert "c-chain-rule" in cids  # fetched missing backtrack prerequisite from Postgres
    assert cids.index("c-backprop") < cids.index("c-fresh")
    by_cid = {item.concept_id: item for item in resp.items}
    assert by_cid["c-chain-rule"].badge == "Revisit"
    assert by_cid["c-chain-rule"].ranking_reason == "prereq_backtrack"
    assert by_cid["c-backprop"].badge == "Revisit"
    assert by_cid["c-fresh"].badge is None
    assert "quiz-cr-1" in ids
