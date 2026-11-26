"""Creative cards in the feed: only relevant, never a repeat of one answered recently, and duel
picks become knowledge-map evidence."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.middleware import get_current_user
from backend.models.feed_schemas import FeedItem, FeedItemType
from backend.routers import feed as feed_router


def _item(name: str, i: int = 0) -> FeedItem:
    return FeedItem(id=f"f{i}", item_type=FeedItemType.TERM_CARD, content={}, concept_id=f"c{i}",
                    concept_name=name, domain="AI & ML", priority_score=0.5)


class _Pg:
    def __init__(self, answered_source_ids: list[str]):
        self.rows = [{"source_id": s} for s in answered_source_ids]
        self.calls = 0

    async def execute_query(self, sql, params=None):
        self.calls += 1
        return self.rows


def _run(items, pg, **req):
    response = SimpleNamespace(items=list(items))
    request = SimpleNamespace(user_id="00000000-0000-0000-0000-000000000001", max_items=20,
                              item_types=None, domains=None, **req)
    asyncio.run(feed_router._add_creative_card(response, request, pg))
    return [i for i in response.items if i.item_type in (FeedItemType.SPOT_THE_BUG, FeedItemType.TRADEOFF_DUEL)]


def test_no_creative_card_when_nothing_in_the_feed_matches() -> None:
    """Before: the best of the library was shown even at relevance 0 (e.g. a Redis duel next to geometry)."""
    assert _run([_item("Collinear Points"), _item("Euclidean Algorithm", 1)], _Pg([])) == []


def test_matching_card_is_inserted() -> None:
    cards = _run([_item("Binary Search"), _item("Two Pointers", 1)], _Pg([]))
    assert len(cards) == 1 and cards[0].id == "spot_the_bug:bug-binary-search-loop"


def test_card_answered_recently_is_not_shown_again() -> None:
    pg = _Pg(["spot_the_bug:bug-binary-search-loop"])
    cards = _run([_item("Binary Search"), _item("Two Pointers", 1)], pg)
    assert pg.calls == 1
    assert all(c.id != "spot_the_bug:bug-binary-search-loop" for c in cards)


@pytest.mark.parametrize("choice,matched,signal", [("a", True, 0.8), ("b", False, 0.4)])
def test_tradeoff_duel_pick_records_quiz_evidence(monkeypatch, choice, matched, signal) -> None:
    add_evidence = AsyncMock()
    monkeypatch.setattr(feed_router.km, "add_evidence", add_evidence)
    monkeypatch.setattr(feed_router.km, "_user_concepts", AsyncMock(return_value=[]))
    monkeypatch.setattr(feed_router, "get_neo4j_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(feed_router, "get_postgres_client", AsyncMock(return_value=object()))
    app = FastAPI()
    app.include_router(feed_router.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "00000000-0000-0000-0000-000000000001"}

    r = TestClient(app).post("/api/feed/tradeoff-duel-pick",
                             json={"card_id": "duel-pgvector-hnsw-vs-ivfflat", "choice": choice})
    assert r.status_code == 200
    assert r.json()["matched"] is matched
    kwargs = add_evidence.await_args.kwargs
    assert kwargs["kind"] == "quiz" and kwargs["signal"] == signal
    assert kwargs["source_id"] == "tradeoff_duel:duel-pgvector-hnsw-vs-ivfflat"


def test_tradeoff_duel_pick_rejects_unknown_card_and_bad_choice(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(feed_router.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "00000000-0000-0000-0000-000000000001"}
    client = TestClient(app)
    assert client.post("/api/feed/tradeoff-duel-pick", json={"card_id": "nope", "choice": "a"}).status_code == 404
    assert client.post("/api/feed/tradeoff-duel-pick",
                       json={"card_id": "duel-pgvector-hnsw-vs-ivfflat", "choice": "c"}).status_code == 422


def test_repeated_feed_concepts_do_not_inflate_relevance() -> None:
    """Live case: "Multi-Query Attention" twice in the feed scored the cross-encoder/RRF duel's
    single shared word ("query") twice, enough to clear the bar."""
    items = [_item("Multi-Query Attention", 0), _item("Multi-Query Attention", 1), _item("Greatest Common Divisor", 2)]
    assert all(c.id != "tradeoff_duel:duel-cross-encoder-vs-rrf" for c in _run(items, _Pg([])))
