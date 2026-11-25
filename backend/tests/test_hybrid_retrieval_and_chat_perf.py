"""Tests for GraphRecall review fixes 5-7: hybrid chunk RRF, windowing, bounded chat LLMs, and FTS5/tsvector."""

from __future__ import annotations

import asyncio
import importlib
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

importlib.import_module("backend.graphs.chat_graph")
cg = sys.modules["backend.graphs.chat_graph"]
from backend.models.feed_schemas import ChatRequest
from backend.services.retrieval_service import (
    RetrievalService,
    dedupe_by_parent,
    extract_child_centered_window,
    pack_context_chunks,
    reciprocal_rank_fusion,
)
from backend.tests.test_migrate import scratch_db  # noqa: F401 (pytest fixture)


def test_reciprocal_rank_fusion_chunk_id_space() -> None:
    vector = [
        {"id": "c1", "parent_chunk_id": "p1", "title": "Note A", "content": "alpha", "similarity": 0.91},
        {"id": "c2", "parent_chunk_id": "p2", "title": "Note B", "content": "beta", "similarity": 0.85},
        {"id": "c3", "parent_chunk_id": "p3", "title": "Note C", "content": "gamma", "similarity": 0.79},
    ]
    keyword = [
        {"id": "c3", "parent_chunk_id": "p3", "title": "Note C", "content": "gamma"},
        {"id": "c4", "parent_chunk_id": "p4", "title": "Note D", "content": "delta"},
    ]
    graph = [
        {"id": "c3", "parent_chunk_id": "p3", "title": "Note C", "content": "gamma"},
        {"id": "c2", "parent_chunk_id": "p2", "title": "Note B", "content": "beta"},
    ]

    fused = reciprocal_rank_fusion([("vector", 1.0, vector), ("keyword", 0.85, keyword), ("graph", 0.65, graph)])
    assert fused[0]["id"] == "c3"
    assert fused[0]["_matched_by"] == ["vector", "keyword", "graph"]
    assert fused[1]["id"] == "c2"


def test_dedupe_by_parent_merges_signals() -> None:
    candidates = [
        {"id": "c1", "parent_chunk_id": "p1", "content": "p1 full", "_matched_by": ["vector"], "_rrf_score": 0.04},
        {"id": "c2", "parent_chunk_id": "p1", "content": "p1 full", "_matched_by": ["keyword"], "_rrf_score": 0.03},
        {"id": "c3", "parent_chunk_id": "p2", "content": "p2 full", "_matched_by": ["vector"], "_rrf_score": 0.02},
    ]
    deduped = dedupe_by_parent(candidates, limit=5)
    assert [item["id"] for item in deduped] == ["c1", "c3"]
    assert set(deduped[0]["_matched_by"]) == {"vector", "keyword"}


def test_child_centered_window_preserves_late_evidence() -> None:
    prefix = ("filler word " * 90)[:940]
    needle = "NEEDLE: FSRS uses stability and difficulty rather than fixed ease factor."
    suffix = " trailing explanation about retention curves and intervals." * 12
    parent = prefix + needle + suffix

    window = extract_child_centered_window(parent, needle, window_chars=700, radius_chars=220)
    assert needle in window
    assert len(window) <= 720
    # Short parents remain verbatim.
    short_parent = "Concise parent chunk under window limit."
    assert extract_child_centered_window(short_parent, "Concise", window_chars=700) == short_parent


def test_pack_context_chunks_enforces_char_budget() -> None:
    chunks = [
        {"id": f"c{i}", "parent_content": "X " * 500, "child_content": "X " * 40}
        for i in range(4)
    ]
    packed = pack_context_chunks(chunks, max_chars=1800, per_chunk_window=900)
    assert len(packed) == 2
    assert sum(len(item["window_content"]) for item in packed) <= 1800


def test_chat_request_rejects_oversized_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(user_id="u1", message="x" * 8001)
    assert ChatRequest(user_id="u1", message="valid question").message == "valid question"


@pytest.mark.asyncio
async def test_analyze_query_parallel_embed_and_greeting_fastpath() -> None:
    cg._QUERY_EMBED_CACHE.clear()
    embed_started = asyncio.Event()
    embed_calls = 0
    llm_calls = 0

    class FakeEmbedder:
        async def aembed_query(self, text: str, **kwargs):
            nonlocal embed_calls
            embed_calls += 1
            embed_started.set()
            return [0.25] * 8

    async def fake_intent_ainvoke(msgs):
        nonlocal llm_calls
        llm_calls += 1
        # Fails with TimeoutError if analyze_query_node ran intent sequentially before starting embed.
        await asyncio.wait_for(embed_started.wait(), timeout=1.0)
        return cg.QueryAnalysis(intent="explain", entities=["HNSW"], needs_search=True)

    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=fake_intent_ainvoke)

    with patch.object(cg, "get_embeddings", return_value=FakeEmbedder()), \
         patch.object(cg, "get_embedding_dims", return_value=8), \
         patch.object(cg, "get_fast_model", return_value=fake_llm):
        greet = await cg.analyze_query_node({"messages": [HumanMessage(content="hello!")]})
        assert greet == {"intent": "general", "entities": [], "router_source": "greeting"}
        assert llm_calls == 0
        assert embed_calls == 0

        analyzed = await cg.analyze_query_node({"messages": [HumanMessage(content="Explain HNSW iterative scan")]})
        assert analyzed == {"intent": "explain", "entities": ["HNSW"], "router_source": "llm"}
        assert llm_calls == 1
        assert embed_calls == 1


@pytest.mark.asyncio
async def test_get_context_skips_map_reduce_on_general_and_caps_summarize() -> None:
    cg._QUERY_EMBED_CACHE.clear()
    map_calls = 0
    summaries = [
        {"title": f"Topic {i}", "size": 5 + i, "summary": f"Overview of topic {i} including RRF fusion" if i in (2, 7) else f"Other text {i}"}
        for i in range(10)
    ]

    class FakeCommunitySvc:
        async def get_community_summaries_by_level(self, user_id: str, level: int | None = None):
            return summaries

    async def fake_map_ainvoke(prompt: str):
        nonlocal map_calls
        map_calls += 1
        return AIMessage(content="SCORE: 8\nANSWER: Relevant summary.")

    fake_map_llm = MagicMock()
    fake_map_llm.ainvoke = AsyncMock(side_effect=fake_map_ainvoke)

    fake_embedder = MagicMock()
    fake_embedder.aembed_query = AsyncMock(return_value=[0.1] * 8)
    mock_pg = AsyncMock()
    mock_pg.execute_query = AsyncMock(return_value=[])
    mock_neo4j = AsyncMock()
    mock_neo4j.find_seed_concepts = AsyncMock(return_value=[])
    mock_neo4j.execute_query = AsyncMock(return_value=[])

    with patch.object(cg, "get_embeddings", return_value=fake_embedder), \
         patch.object(cg, "get_embedding_dims", return_value=8), \
         patch.object(cg, "get_postgres_client", new=AsyncMock(return_value=mock_pg)), \
         patch.object(cg, "get_neo4j_client", new=AsyncMock(return_value=mock_neo4j)), \
         patch.object(cg, "get_fast_model", return_value=fake_map_llm), \
         patch("backend.services.community_service.CommunityService", FakeCommunitySvc):
        out_general = await cg.get_context_node({
            "user_id": "u1",
            "intent": "general",
            "entities": [],
            "messages": [HumanMessage(content="how are you?")],
        })
        assert map_calls == 0
        assert "global_summary" not in out_general["graph_context"]

        out_summarize = await cg.get_context_node({
            "user_id": "u1",
            "intent": "summarize",
            "entities": [],
            "messages": [HumanMessage(content="Summarize RRF fusion")],
        })
        assert 1 <= map_calls <= cg._MAX_GLOBAL_MAP_CALLS
        assert out_summarize["graph_context"]["search_mode"] == "global_map_reduce"


@pytest.mark.asyncio
async def test_generate_response_static_first_prompt_and_late_child_window() -> None:
    captured_prompts: list[list] = []

    class FakeResponseLLM:
        def with_config(self, cfg):
            return self

        async def ainvoke(self, messages):
            captured_prompts.append(messages)
            return AIMessage(content="Cited answer [1].")

    late_needle = "EVIDENCE_CHAR_950: pgvector HNSW uses iterative scan for filtered queries."
    long_parent = ("Opening intro filler text. " * 40)[:940] + late_needle + " Rest of section."

    with patch.object(cg, "get_chat_model", return_value=FakeResponseLLM()):
        out1 = await cg.generate_response_node({
            "user_id": "u1",
            "intent": "explain",
            "entities": ["HNSW"],
            "messages": [HumanMessage(content="How does filtered ANN work?")],
            "graph_context": {"concepts": [], "relationships": [], "retrieval_stats": {"vector": 1, "keyword": 1}},
            "rag_context": [{
                "id": "c1",
                "parent_chunk_id": "p1",
                "title": "Vector Indexing",
                "parent_content": long_parent,
                "child_content": late_needle,
                "content": long_parent,
                "images": [],
                "_matched_by": ["vector", "keyword"],
                "_rrf_score": 0.031,
            }],
        })
        out2 = await cg.generate_response_node({
            "user_id": "u2",
            "intent": "compare",
            "entities": ["BM25"],
            "messages": [HumanMessage(content="Compare BM25 and dense vectors")],
            "graph_context": {"concepts": [], "relationships": []},
            "rag_context": [],
        })

    assert len(captured_prompts) == 2
    sys1, dyn1 = captured_prompts[0][0], captured_prompts[0][1]
    sys2, _ = captured_prompts[1][0], captured_prompts[1][1]
    assert isinstance(sys1, SystemMessage) and isinstance(sys2, SystemMessage)
    assert sys1.content == sys2.content
    assert late_needle in dyn1.content
    assert late_needle in out1["sources"][0]["content"]
    assert out1["metadata"]["retrieval_mode"] == "hybrid_rrf"
    assert out2["messages"][-1].content == "Cited answer [1]."


@pytest.mark.asyncio
async def test_real_postgres_keyword_search_and_tenant_isolation(scratch_db) -> None:  # noqa: F811
    from backend.db import migrate as M

    pg, _ = scratch_db
    await M.migrate(pg)

    idx_rows = await pg.execute_query(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'chunks' AND indexname = 'idx_chunks_content_tsv'"
    )
    assert len(idx_rows) == 1

    user_a = (await pg.execute_query(
        "INSERT INTO users (email) VALUES (:e) RETURNING id",
        {"e": f"a-{uuid.uuid4().hex[:6]}@example.invalid"},
    ))[0]["id"]
    user_b = (await pg.execute_query(
        "INSERT INTO users (email) VALUES (:e) RETURNING id",
        {"e": f"b-{uuid.uuid4().hex[:6]}@example.invalid"},
    ))[0]["id"]

    note_a = (await pg.execute_query(
        "INSERT INTO notes (user_id, title, content_text) VALUES (:u, 'Retrieval Note', 'A') RETURNING id",
        {"u": user_a},
    ))[0]["id"]
    note_b = (await pg.execute_query(
        "INSERT INTO notes (user_id, title, content_text) VALUES (:u, 'Secret Note B', 'B') RETURNING id",
        {"u": user_b},
    ))[0]["id"]

    p_a = (await pg.execute_query(
        "INSERT INTO chunks (note_id, chunk_index, content, chunk_level) "
        "VALUES (:n, 0, 'Parent intro followed by BM25 reciprocal rank fusion details.', 'parent') RETURNING id",
        {"n": note_a},
    ))[0]["id"]
    p_b = (await pg.execute_query(
        "INSERT INTO chunks (note_id, chunk_index, content, chunk_level) "
        "VALUES (:n, 0, 'Tenant B secret BM25 reciprocal rank payload.', 'parent') RETURNING id",
        {"n": note_b},
    ))[0]["id"]

    c_a = (await pg.execute_query(
        "INSERT INTO chunks (note_id, parent_chunk_id, chunk_index, content, chunk_level) "
        "VALUES (:n, :p, 1, 'BM25 reciprocal rank fusion combines lexical and dense hits.', 'child') RETURNING id",
        {"n": note_a, "p": p_a},
    ))[0]["id"]
    await pg.execute_query(
        "INSERT INTO chunks (note_id, parent_chunk_id, chunk_index, content, chunk_level) "
        "VALUES (:n, :p, 1, 'Tenant B secret BM25 reciprocal rank payload.', 'child') RETURNING id",
        {"n": note_b, "p": p_b},
    )

    out = await RetrievalService().hybrid_search(
        query="BM25 reciprocal rank",
        user_id=str(user_a),
        query_embedding=None,
        limit=5,
        pg_client=pg,
    )
    assert out["stats"]["keyword"] == 1
    assert [str(c["id"]) for c in out["chunks"]] == [str(c_a)]
    assert out["chunks"][0]["_matched_by"] == ["keyword"]
