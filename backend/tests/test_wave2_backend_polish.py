"""Pure unit tests for Wave 2 backend polish:
1. graph3d N+1 query batching (Neo4j UNWIND count + Postgres ANY(:ids) notes/chunks) & user_id scoping
2. later digest endpoints (/api/later/digest-url and /api/later/{id}/digest)
3. feed creative-cards & spot-the-bug-grade endpoints
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.auth.middleware import get_current_user
from backend.routers import feed as feed_router
from backend.routers import graph3d as graph3d_router
from backend.routers import later as later_router


def _make_client(router, user_id: str = "11111111-1111-1111-1111-111111111111") -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id, "email": "u@example.com"}
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Graph3D N+1 batching & tenant scoping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_graph3d_batches_relationship_counts_into_single_cypher_query(monkeypatch):
    concepts = [
        {
            "id": f"c-{i}",
            "name": f"Concept {i}",
            "definition": f"Def {i}",
            "domain": "Computer Science",
            "complexity_score": 5,
        }
        for i in range(20)
    ]
    recorded_neo4j: list[tuple[str, dict]] = []

    async def fake_neo_exec(query: str, params=None):
        recorded_neo4j.append((query, dict(params or {})))
        if "RETURN c as concept" in query:
            return [{"concept": c} for c in concepts]
        if "UNWIND $ids AS cid" in query:
            assert params["user_id"] == "user-abc"
            assert len(params["ids"]) == 20
            return [{"id": f"c-{i}", "count": i % 5} for i in range(20)]
        return []

    mock_neo4j = AsyncMock()
    mock_neo4j.execute_query = AsyncMock(side_effect=fake_neo_exec)

    mock_pg = AsyncMock()
    mock_pg.execute_query = AsyncMock(return_value=[])

    async def fake_get_neo4j():
        return mock_neo4j

    async def fake_get_pg():
        return mock_pg

    async def fake_get_communities(self, user_id: str):
        return []

    monkeypatch.setattr(graph3d_router, "get_neo4j_client", fake_get_neo4j)
    monkeypatch.setattr(graph3d_router, "get_postgres_client", fake_get_pg)
    monkeypatch.setattr(graph3d_router.CommunityService, "get_communities", fake_get_communities)

    resp = await graph3d_router.get_3d_graph(current_user={"id": "user-abc"}, center_concept_id=None, max_depth=3)

    assert resp.total_nodes == 20
    count_queries = [(q, p) for q, p in recorded_neo4j if "count(r)" in q]
    assert len(count_queries) == 1, f"Expected 1 batched count query, got {len(count_queries)}"
    assert "UNWIND $ids AS cid" in count_queries[0][0]
    assert "user_id: $user_id" in count_queries[0][0]
    assert count_queries[0][1]["user_id"] == "user-abc"
    node_map = {n.id: n for n in resp.nodes}
    assert node_map["c-4"].size == graph3d_router.calculate_node_size(5, 4)


@pytest.mark.asyncio
async def test_graph3d_skips_count_query_when_no_concepts(monkeypatch):
    recorded_neo4j: list[str] = []

    async def fake_neo_exec(query: str, params=None):
        recorded_neo4j.append(query)
        return []

    mock_neo4j = AsyncMock()
    mock_neo4j.execute_query = AsyncMock(side_effect=fake_neo_exec)
    mock_pg = AsyncMock()
    mock_pg.execute_query = AsyncMock(return_value=[])

    monkeypatch.setattr(graph3d_router, "get_neo4j_client", AsyncMock(return_value=mock_neo4j))
    monkeypatch.setattr(graph3d_router, "get_postgres_client", AsyncMock(return_value=mock_pg))
    monkeypatch.setattr(graph3d_router.CommunityService, "get_communities", AsyncMock(return_value=[]))

    resp = await graph3d_router.get_3d_graph(current_user={"id": "user-empty"}, center_concept_id=None, max_depth=3)
    assert resp.total_nodes == 0
    assert not any("count(r)" in q for q in recorded_neo4j)


@pytest.mark.asyncio
async def test_focus_on_concept_batches_linked_notes_and_images(monkeypatch):
    pg_calls: list[tuple[str, dict]] = []

    async def fake_neo_exec(query: str, params=None):
        assert params.get("user_id") == "user-1"
        if "RETURN c" in query:
            return [{"c": {"id": "c1", "name": "HNSW", "definition": "ANN graph", "domain": "Database Systems"}}]
        if "EXPLAINS" in query:
            return [
                {"note_id": f"n-{i}", "summary": f"Sum {i}", "relevance": 0.9 - i * 0.1, "evidence_span": f"Span {i}"}
                for i in range(5)
            ]
        return []

    async def fake_pg_exec(query: str, params=None):
        pg_calls.append((query, dict(params or {})))
        # Every query must be owner-filtered; knowledge_map names the parameter :u.
        assert (params.get("user_id") or params.get("u")) == "user-1"
        if "FROM notes" in query:
            assert "= ANY(:ids)" in query
            return [
                {
                    "id": f"n-{i}",
                    "title": f"Note {i}",
                    "content_text": f"Full {i}",
                    "resource_type": "article",
                    "created_at": "2026-11-25",
                }
                for i in range(5)
            ]
        if "FROM chunks" in query:
            assert "= ANY(:ids)" in query
            assert "n.user_id = :user_id" in query
            return [
                {"note_id": "n-0", "images": [{"url": "https://cdn.example.com/a.png"}]},
                {"note_id": "n-2", "images": [{"url": "https://cdn.example.com/b.png"}]},
            ]
        return []

    mock_neo4j = AsyncMock()
    mock_neo4j.execute_query = AsyncMock(side_effect=fake_neo_exec)
    mock_pg = AsyncMock()
    mock_pg.execute_query = AsyncMock(side_effect=fake_pg_exec)

    monkeypatch.setattr(graph3d_router, "get_neo4j_client", AsyncMock(return_value=mock_neo4j))
    monkeypatch.setattr(graph3d_router, "get_postgres_client", AsyncMock(return_value=mock_pg))

    res = await graph3d_router.focus_on_concept("c1", current_user={"id": "user-1"})
    assert len(res["linked_notes"]) == 5
    assert res["linked_notes"][0]["images"] == [{"url": "https://cdn.example.com/a.png"}]
    assert res["linked_notes"][2]["images"] == [{"url": "https://cdn.example.com/b.png"}]

    note_queries = [q for q, _ in pg_calls if "FROM notes" in q]
    chunk_queries = [q for q, _ in pg_calls if "FROM chunks" in q]
    # No N+1: every notes/chunks query is batched over ids, and their number does not grow with the
    # 5 linked notes (linked notes + provenance each read notes once).
    assert all("ANY(:ids)" in q for q in note_queries + chunk_queries)
    assert len(note_queries) <= 2 and len(chunk_queries) == 1


# ---------------------------------------------------------------------------
# 2. Later Digest Endpoints
# ---------------------------------------------------------------------------

def test_later_digest_url_rejects_unsafe_schemes():
    client = _make_client(later_router.router)
    for bad in ("javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "file:///etc/passwd"):
        r = client.post("/api/later/digest-url", json={"url": bad, "text": "Some article"})
        assert r.status_code == 422, f"Expected 422 for {bad}, got {r.status_code}"


def test_later_digest_url_extracts_diagrams_claims_and_handles_missing_db(monkeypatch):
    async def fail_pg():
        raise RuntimeError("pool not initialized")

    monkeypatch.setattr(later_router, "get_postgres_client", fail_pg)
    client = _make_client(later_router.router)

    article = """# Hybrid Search Deep Dive

**HNSW**: Hierarchical Navigable Small World graph index for approximate nearest neighbors.

- Always apply tenant filters before vector LIMIT clauses in multi-tenant Postgres deployments.

```mermaid
flowchart LR
    Q["Query Vector"] --> H[HNSW Index Scan]
    H --> R[Cross-Encoder Reranker]
```

![Hybrid retrieval architecture overview](https://cdn.example.com/hybrid.png)
"""
    r = client.post(
        "/api/later/digest-url",
        json={"url": "https://example.com/hybrid-rag", "text": article, "title": "Hybrid RAG"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["digested"] is True
    assert data["diagram_count"] == 2
    assert data["card_count"] >= 3
    assert data["queued_job_id"] is None
    assert data["plan"]["source_url"] == "https://example.com/hybrid-rag"
    assert len(data["plan"]["claims"]) >= 1
    assert "HNSW" in data["plan"]["terms"]


def test_later_digest_url_enqueues_durable_job_when_db_available(monkeypatch):
    mock_pg = AsyncMock()
    enqueue_calls: list[dict] = []

    async def fake_enqueue(user_id, job_type, payload, **kwargs):
        enqueue_calls.append({"user_id": user_id, "job_type": job_type, "payload": payload, **kwargs})
        return SimpleNamespace(id="job-digest-42")

    monkeypatch.setattr(later_router, "get_postgres_client", AsyncMock(return_value=mock_pg))
    monkeypatch.setattr(later_router, "enqueue_durable_job", fake_enqueue)

    client = _make_client(later_router.router, user_id="user-digest-1")
    r = client.post(
        "/api/later/digest-url",
        json={
            "url": "https://example.com/post",
            "text": "- Key point about prompt prefix caching and KV cache invalidation.",
            "title": "KV Cache",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["digested"] is True
    assert data["queued_job_id"] == "job-digest-42"
    assert len(enqueue_calls) == 1
    assert enqueue_calls[0]["job_type"] == "article.digest"
    assert enqueue_calls[0]["user_id"] == "user-digest-1"


def test_later_item_digest_checks_ownership_and_marks_done(monkeypatch):
    executed: list[tuple[str, dict]] = []

    async def fake_pg_exec(query: str, params=None):
        executed.append((query, dict(params or {})))
        if params.get("id") == "item-owned" and params.get("u") == "owner-1":
            return [
                {
                    "id": "item-owned",
                    "text": "- Remember to check pgvector iterative_scan for multi-tenant recall.",
                    "url": "https://example.com/pgvector",
                    "source": "share",
                    "when_phrase": "tomorrow",
                    "show_at": "2026-11-26T09:00:00+00:00",
                    "shown_at": None,
                    "created_at": "2026-11-25T10:00:00+00:00",
                }
            ]
        return []

    mock_pg = AsyncMock()
    mock_pg.execute_query = AsyncMock(side_effect=fake_pg_exec)
    monkeypatch.setattr(later_router, "get_postgres_client", AsyncMock(return_value=mock_pg))
    monkeypatch.setattr(
        later_router,
        "enqueue_durable_job",
        AsyncMock(return_value=SimpleNamespace(id="job-item-99")),
    )

    owner_client = _make_client(later_router.router, user_id="owner-1")
    missing_resp = owner_client.post("/api/later/other-users-item/digest")
    assert missing_resp.status_code == 404

    ok_resp = owner_client.post("/api/later/item-owned/digest")
    assert ok_resp.status_code == 200
    body = ok_resp.json()
    assert body["digested"] is True
    assert body["queued_job_id"] == "job-item-99"
    assert body["card_count"] >= 1

    lookup_sql, lookup_params = executed[-1]
    # Ownership is checked, but the item is NOT marked done at enqueue: the worker does that only after
    # the article is actually ingested (a failed digest must not make the item disappear).
    assert "done_at = now()" not in lookup_sql
    assert "user_id = CAST(:u AS uuid)" in lookup_sql
    assert lookup_params == {"id": "item-owned", "u": "owner-1"}


async def test_article_digest_worker_ingests_then_marks_item_done(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from backend.agent_v2 import worker as w

    ingested, updates = {}, []

    async def fake_run_ingestion(**kw):
        ingested.update(kw)
        return {"note_id": "11111111-1111-1111-1111-111111111111", "concept_ids": ["a", "b"]}

    class PG:
        async def execute_update(self, q, p):
            updates.append((q, p))

    job = SimpleNamespace(id="j1", user_id="owner-1", job_type="article.digest",
                          payload={"title": "Attention", "text": "x" * 300, "item_id": "item-9"})
    with patch("backend.graphs.ingestion_graph.run_ingestion", side_effect=fake_run_ingestion), \
         patch("backend.db.postgres_client.get_postgres_client", AsyncMock(return_value=PG())), \
         patch.object(w, "_record_skipped_run", AsyncMock()):
        await w.handle_article_digest(job, runs=None)
    assert ingested["user_id"] == "owner-1" and ingested["resource_type"] == "article"
    assert updates and "done_at = now()" in updates[0][0] and updates[0][1]["id"] == "item-9"


async def test_article_digest_worker_failure_leaves_item_open(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    import pytest as _pytest

    from backend.agent_v2 import worker as w

    job = SimpleNamespace(id="j2", user_id="owner-1", job_type="article.digest",
                          payload={"title": "t", "text": "short", "item_id": "item-9"})
    with patch.object(w, "_record_failed_run", AsyncMock()) as failed:
        with _pytest.raises(ValueError):
            await w.handle_article_digest(job, runs=None)
    failed.assert_awaited()


# ---------------------------------------------------------------------------
# 3. Feed Creative Cards & Spot-The-Bug Grading
# ---------------------------------------------------------------------------

def test_feed_creative_cards_requires_auth():
    app = FastAPI()
    app.include_router(feed_router.router)
    unauthed = TestClient(app)
    r = unauthed.get("/api/feed/creative-cards")
    assert r.status_code in (401, 403)


def test_feed_creative_cards_selects_matched_spot_and_duel_cards(monkeypatch):
    async def fake_pg_exec(query: str, params=None):
        assert params["user_id"] == "user-cc"
        return [{"concept_id": "c-weak"}]

    async def fake_neo_exec(query: str, params=None):
        assert params["user_id"] == "user-cc"
        return [
            {"id": "c-weak", "name": "pgvector multi-tenant", "domain": "Database Systems"},
            {"id": "c-2", "name": "Cross-Encoder RRF", "domain": "RAG"},
        ]

    mock_pg = AsyncMock()
    mock_pg.execute_query = AsyncMock(side_effect=fake_pg_exec)
    mock_neo4j = AsyncMock()
    mock_neo4j.execute_query = AsyncMock(side_effect=fake_neo_exec)

    monkeypatch.setattr(feed_router, "get_postgres_client", AsyncMock(return_value=mock_pg))
    monkeypatch.setattr(feed_router, "get_neo4j_client", AsyncMock(return_value=mock_neo4j))

    client = _make_client(feed_router.router, user_id="user-cc")
    r = client.get("/api/feed/creative-cards")
    assert r.status_code == 200
    data = r.json()
    assert len(data["spot_the_bug"]) >= 1
    assert len(data["tradeoff_duel"]) >= 1
    assert {c["card_type"] for c in data["cards"]} == {"spot_the_bug", "tradeoff_duel"}
    assert data["spot_the_bug"][0]["id"] == "bug-post-ann-filter"
    assert data["tradeoff_duel"][0]["id"] in {"duel-pgvector-hnsw-vs-ivfflat", "duel-cross-encoder-vs-rrf"}


def test_feed_spot_the_bug_grade_unknown_404_and_records_evidence(monkeypatch):
    evidence_calls: list[dict] = []

    async def fake_add_evidence(pg, user_id, **kwargs):
        evidence_calls.append({"pg": pg, "user_id": user_id, **kwargs})

    mock_pg = AsyncMock()
    mock_neo4j = AsyncMock()
    mock_neo4j.execute_query = AsyncMock(
        return_value=[{"id": "concept-ann", "name": "Multi-Tenant Vector Search", "domain": "Database Systems"}]
    )

    monkeypatch.setattr(feed_router, "get_postgres_client", AsyncMock(return_value=mock_pg))
    monkeypatch.setattr(feed_router, "get_neo4j_client", AsyncMock(return_value=mock_neo4j))
    monkeypatch.setattr(feed_router.km, "add_evidence", fake_add_evidence)

    client = _make_client(feed_router.router, user_id="user-grade-1")

    not_found = client.post("/api/feed/spot-the-bug-grade", json={"card_id": "nonexistent-card", "selected_line": 1})
    assert not_found.status_code == 404

    ok = client.post("/api/feed/spot-the-bug-grade", json={"card_id": "bug-post-ann-filter", "selected_line": 5})
    assert ok.status_code == 200
    body = ok.json()
    assert body["correct"] is True
    assert body["recorded"] is True
    assert body["concept_id"] == "concept-ann"
    assert body["evidence"]["signal_type"] == "quiz_correct"
    assert body["evidence"]["score"] == 0.85

    wrong = client.post("/api/feed/spot-the-bug-grade", json={"card_id": "bug-post-ann-filter", "selected_line": 1})
    assert wrong.status_code == 200
    assert wrong.json()["correct"] is False
    assert wrong.json()["evidence"]["score"] == 0.10

    assert len(evidence_calls) == 2
    assert evidence_calls[0]["user_id"] == "user-grade-1"
    assert evidence_calls[0]["kind"] == "quiz"
    assert evidence_calls[0]["signal"] == 0.85
    assert evidence_calls[0]["concept_id"] == "concept-ann"
    assert evidence_calls[1]["user_id"] == "user-grade-1"
    assert evidence_calls[1]["kind"] == "quiz"
    assert evidence_calls[1]["signal"] == 0.10
