"""Pure-unit tests for Step #9 Chat RAG pipeline wiring and bug fixes."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

importlib.import_module("backend.graphs.chat_graph")
cg = sys.modules["backend.graphs.chat_graph"]

from backend.models.feed_schemas import ChatRequest
from backend.routers import chat as chat_router
from backend.services.intent_router import router as ir
from backend.services.rag_cache import (
    CorpusVersionedResponseCache,
    EmbeddingCache,
    InMemoryTTLCache,
    RedisCacheBackend,
)


class _DummyEmbedder:
    def __init__(self, dims: int = 8) -> None:
        self.dims = dims
        self.calls: list[str] = []

    async def aembed_query(self, text: str, **kwargs):
        self.calls.append(text)
        return [float(i + 1) / 10.0 for i in range(self.dims)]


@pytest.fixture(autouse=True)
def _reset_chat_caches():
    cg._QUERY_EMBED_CACHE.clear()
    cg._RESPONSE_CACHE = CorpusVersionedResponseCache(backend=InMemoryTTLCache(max_entries=128))
    yield
    cg._QUERY_EMBED_CACHE.clear()
    cg._RESPONSE_CACHE = None


@pytest.mark.asyncio
async def test_multimodal_and_none_message_content_normalized(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_INTENT_ROUTER", "model")
    monkeypatch.setenv("CHAT_INTENT_THRESHOLD", "0.3")
    embedder = _DummyEmbedder(dims=8)

    with patch.object(cg, "get_embeddings", return_value=embedder), \
         patch.object(cg, "get_embedding_dims", return_value=8), \
         patch.object(ir, "mentioned_concepts", AsyncMock(return_value=["HNSW"])), \
         patch.object(ir, "log_decision"):
        # Multimodal greeting list -> greeting fast-path without crashing
        greet = await cg.analyze_query_node({
            "messages": [HumanMessage(content=[{"type": "text", "text": "hello!"}])],
            "user_id": "u1",
            "retrieval_query": "stale query",
        })
        assert greet == {
            "intent": "general",
            "entities": [],
            "router_source": "greeting",
            "retrieval_query": "hello!",
        }

        # Multimodal non-greeting content -> flattened to text cleanly
        analyzed = await cg.analyze_query_node({
            "messages": [
                HumanMessage(content=[
                    {"type": "text", "text": "Explain"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/fig.png"}},
                    {"type": "text", "text": "HNSW"},
                ])
            ],
            "user_id": "u1",
        })
        assert analyzed["retrieval_query"] == "Explain HNSW"
        assert embedder.calls == ["Explain HNSW"]

    assert cg._extract_text(None) == ""
    assert cg._extract_text(["plain", {"type": "text", "text": "block"}]) == "plain block"


@pytest.mark.asyncio
async def test_retrieval_query_reset_and_greeting_history_filtering(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_INTENT_ROUTER", "model")
    monkeypatch.setenv("CHAT_INTENT_THRESHOLD", "1.01")
    embedder = _DummyEmbedder(dims=8)

    failing_llm = MagicMock()
    failing_llm.with_structured_output.return_value.ainvoke = AsyncMock(
        side_effect=asyncio.TimeoutError()
    )

    mentioned_args: list[str] = []

    async def fake_mentioned(user_id: str, q: str) -> list[str]:
        mentioned_args.append(q)
        return ["LoRA"]

    with patch.object(cg, "get_embeddings", return_value=embedder), \
         patch.object(cg, "get_embedding_dims", return_value=8), \
         patch.object(cg, "get_fast_model", return_value=failing_llm), \
         patch.object(ir, "mentioned_concepts", side_effect=fake_mentioned), \
         patch.object(ir, "log_decision"):
        # Greeting turn in between must be filtered out of `earlier` so follow-up anchors to "Explain LoRA".
        # Also verifies LLM failure fallback passes `retrieval_query` consistently.
        res = await cg.analyze_query_node({
            "user_id": "u1",
            "entities": ["LoRA"],
            "messages": [
                HumanMessage(content="Explain LoRA"),
                AIMessage(content="LoRA uses low-rank adapters."),
                HumanMessage(content="thanks!"),
                HumanMessage(content="what are its limitations?"),
            ],
            "retrieval_query": "stale",
        })
        assert res["retrieval_query"] == "what are its limitations? LoRA"
        assert mentioned_args == ["what are its limitations? LoRA"]

        # Empty messages resets stale retrieval_query
        empty_res = await cg.analyze_query_node({"messages": [], "retrieval_query": "stale"})
        assert empty_res == {"intent": "general", "entities": [], "retrieval_query": ""}


@pytest.mark.asyncio
async def test_run_chat_and_stream_chat_reset_retrieval_query_and_emit_cached_stream() -> None:
    captured_states: list[dict] = []

    async def fake_ainvoke(initial_state, config):
        captured_states.append(dict(initial_state))
        return {
            "messages": [AIMessage(content="Cached answer [1].")],
            "sources": [],
            "related_concepts": [],
            "metadata": {"cache_hit": True},
        }

    with patch.object(cg.chat_graph, "ainvoke", side_effect=fake_ainvoke):
        out = await cg.run_chat(user_id="u1", message="hi", thread_id=cg.chat_thread_id("u1"))
    assert captured_states[0]["retrieval_query"] == "hi"
    assert out["response"] == "Cached answer [1]."

    # Verify stream_chat sets retrieval_query in initial_state and emits chunk on L2 cache hit (no LLM stream)
    stream_initial_states: list[dict] = []

    async def fake_astream_events(initial_state, config, version="v2"):
        stream_initial_states.append(dict(initial_state))
        yield {"event": "on_chain_start", "name": "generate_response", "data": {}}
        yield {"event": "on_chain_end", "name": "generate_response", "data": {}}

    fake_state_snapshot = MagicMock()
    fake_state_snapshot.values = {
        "messages": [AIMessage(content="Cached SSE response [1].")],
        "sources": [{"id": "s1", "title": "Note"}],
        "related_concepts": [],
        "metadata": {"cache_hit": True},
    }

    mock_pg = AsyncMock()
    mock_pg.execute_query = AsyncMock(return_value=[{"id": "conv-1"}])
    mock_pg.execute_insert = AsyncMock(return_value="msg-1")
    mock_pg.execute_update = AsyncMock(return_value=None)

    with patch.object(chat_router, "get_postgres_client", AsyncMock(return_value=mock_pg)), \
         patch.object(chat_router.chat_graph, "astream_events", side_effect=fake_astream_events), \
         patch.object(chat_router.chat_graph, "aget_state", AsyncMock(return_value=fake_state_snapshot)):
        resp = await chat_router.stream_chat(
            request=ChatRequest(user_id="u1", message="Explain HNSW", conversation_id="conv-1"),
            current_user={"id": "u1"},
        )
        events = []
        async for raw in resp.body_iterator:
            text = raw.decode() if isinstance(raw, bytes) else raw
            if text.startswith("data: "):
                events.append(json.loads(text[6:].strip()))

    assert stream_initial_states[0]["retrieval_query"] == "Explain HNSW"
    chunk_events = [e for e in events if e.get("type") == "chunk"]
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(chunk_events) == 1
    assert chunk_events[0]["content"] == "Cached SSE response [1]."
    assert len(done_events) == 1
    assert done_events[0]["metadata"]["cache_hit"] is True


@pytest.mark.asyncio
async def test_l1_embedding_cache_and_backend_selection(monkeypatch) -> None:
    assert isinstance(cg._EMBED_CACHE, EmbeddingCache)
    embedder = _DummyEmbedder(dims=8)

    with patch.object(cg, "get_embeddings", return_value=embedder), \
         patch.object(cg, "get_embedding_dims", return_value=8):
        v1 = await cg._embed_query_cached("  What   is  HNSW? ")
        v2 = await cg._embed_query_cached("what is hnsw?")
        assert v1 == v2
        assert len(embedder.calls) == 1

        cg._QUERY_EMBED_CACHE.clear()
        v3 = await cg._embed_query_cached("what is hnsw?")
        assert v3 == v1
        assert len(embedder.calls) == 2

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    redis_cache = cg._create_embedding_cache()
    assert isinstance(redis_cache._backend, RedisCacheBackend)
    monkeypatch.delenv("REDIS_URL", raising=False)
    mem_cache = cg._create_embedding_cache()
    assert isinstance(mem_cache._backend, InMemoryTTLCache)


@pytest.mark.asyncio
async def test_get_context_node_wires_reranker_mmr_and_lost_in_middle(monkeypatch) -> None:
    monkeypatch.setenv("RERANKER_MODE", "lexical")
    monkeypatch.setenv("RAG_MAX_PER_PARENT", "1")
    embedder = _DummyEmbedder(dims=4)
    mock_pg = AsyncMock()
    mock_neo4j = AsyncMock()
    mock_neo4j.find_seed_concepts = AsyncMock(return_value=[])

    # c1 and c1_dup share parent p1 -> MMR must dedupe them.
    # c3 has exact lexical phrase match for query ("HNSW ef_search") despite lower prior RRF score.
    fake_chunks = [
        {
            "id": "c1",
            "parent_chunk_id": "p1",
            "title": "Vector Basics",
            "content": "Approximate nearest neighbor indexes accelerate vector lookup.",
            "parent_content": "Approximate nearest neighbor indexes accelerate vector lookup.",
            "child_content": "Approximate nearest neighbor",
            "_rrf_score": 0.045,
            "similarity": 0.85,
            "images": [],
        },
        {
            "id": "c1_dup",
            "parent_chunk_id": "p1",
            "title": "Vector Basics",
            "content": "Approximate nearest neighbor indexes accelerate vector lookup.",
            "parent_content": "Approximate nearest neighbor indexes accelerate vector lookup.",
            "child_content": "vector lookup",
            "_rrf_score": 0.030,
            "similarity": 0.80,
            "images": [],
        },
        {
            "id": "c2",
            "parent_chunk_id": "p2",
            "title": "HNSW ef_search tuning",
            "content": "HNSW ef_search controls recall vs latency during graph traversal.",
            "parent_content": "HNSW ef_search controls recall vs latency during graph traversal.",
            "child_content": "HNSW ef_search",
            "_rrf_score": 0.025,
            "similarity": 0.78,
            "images": [],
        },
        {
            "id": "c3",
            "parent_chunk_id": "p3",
            "title": "Postgres GIN",
            "content": "Postgres tsvector indexes support lexical search.",
            "parent_content": "Postgres tsvector indexes support lexical search.",
            "child_content": "tsvector indexes",
            "_rrf_score": 0.020,
            "similarity": 0.65,
            "images": [],
        },
    ]

    with patch.object(cg, "get_embeddings", return_value=embedder), \
         patch.object(cg, "get_embedding_dims", return_value=4), \
         patch.object(cg, "get_postgres_client", AsyncMock(return_value=mock_pg)), \
         patch.object(cg, "get_neo4j_client", AsyncMock(return_value=mock_neo4j)), \
         patch.object(
             cg.RetrievalService,
             "hybrid_search",
             AsyncMock(return_value={"chunks": fake_chunks, "stats": {"vector": 4}}),
         ):
        out = await cg.get_context_node({
            "user_id": "u1",
            "intent": "explain",
            "entities": [],
            "retrieval_query": "HNSW ef_search",
            "messages": [HumanMessage(content="HNSW ef_search")],
        })

    rag = out["rag_context"]
    ids = [c["id"] for c in rag]
    assert len(ids) == 3  # p1 deduplicated
    assert ids[0] == "c2"  # promoted to rank 0 by LexicalOverlapReranker and kept first by lost-in-middle
    assert "rerank_score" in rag[0]
    assert out["graph_context"]["rerank_stats"]["method"] == "lexical_overlap"
    assert out["graph_context"]["rerank_stats"]["in_count"] == 4
    assert out["graph_context"]["rerank_stats"]["out_count"] == 3


@pytest.mark.asyncio
async def test_get_context_node_wires_two_level_onnx_reranker(monkeypatch) -> None:
    from backend.services.reranker import RerankResult

    monkeypatch.setenv("RERANKER_MODE", "onnx")
    monkeypatch.setenv("RAG_MAX_PER_PARENT", "2")
    embedder = _DummyEmbedder(dims=4)
    mock_pg = AsyncMock()
    mock_pg.execute_query = AsyncMock(return_value=[])
    mock_neo4j = AsyncMock()
    mock_neo4j.find_seed_concepts = AsyncMock(return_value=[])

    coarse_chunks = [
        {"id": "c1", "parent_chunk_id": "p1", "title": "Note A", "content": "coarse 1", "child_content": "c1", "_rrf_score": 0.04, "images": []},
        {"id": "c2", "parent_chunk_id": "p1", "title": "Note A", "content": "coarse 2", "child_content": "c2", "_rrf_score": 0.03, "images": []},
        {"id": "c3", "parent_chunk_id": "p2", "title": "Note B", "content": "coarse 3", "child_content": "c3", "_rrf_score": 0.05, "images": []},
    ]
    hybrid_mock = AsyncMock(return_value={"chunks": coarse_chunks, "stats": {"vector": 3}})

    class FakeCEReranker:
        def rerank(self, query: str, chunks: list[dict], top_k: int = 8) -> RerankResult:
            # Promote both c1 and c2 from p1 above c3 using CE scores.
            scored = [
                {**chunks[0], "rerank_score": 4.0},
                {**chunks[1], "rerank_score": 2.5},
                {**chunks[2], "rerank_score": -1.2},
            ]
            return RerankResult(chunks=scored[:top_k], method="onnx_cross_encoder", latency_ms=12.5, used_fallback=False)

    with patch.object(cg, "get_embeddings", return_value=embedder), \
         patch.object(cg, "get_embedding_dims", return_value=4), \
         patch.object(cg, "get_postgres_client", AsyncMock(return_value=mock_pg)), \
         patch.object(cg, "get_neo4j_client", AsyncMock(return_value=mock_neo4j)), \
         patch.object(cg, "get_reranker", return_value=FakeCEReranker()), \
         patch.object(cg.RetrievalService, "hybrid_search", hybrid_mock):
        out = await cg.get_context_node({
            "user_id": "u1",
            "intent": "explain",
            "entities": [],
            "retrieval_query": "HNSW pruning",
            "messages": [HumanMessage(content="HNSW pruning")],
        })

    kwargs = hybrid_mock.await_args.kwargs
    assert kwargs["limit"] == 25
    assert kwargs["candidate_k"] == 25
    assert kwargs["max_per_parent"] == 0
    assert kwargs["attach_embeddings"] is False
    assert [c["id"] for c in out["rag_context"]] == ["c1", "c3", "c2"] or set(c["id"] for c in out["rag_context"]) == {"c1", "c2", "c3"}
    assert out["graph_context"]["rerank_stats"]["method"] == "onnx_cross_encoder"


@pytest.mark.asyncio
async def test_generate_response_l2_cache_hit_invalidation_and_grounding() -> None:
    llm_calls: list[list] = []

    class FakeLLM:
        def with_config(self, cfg):
            return self

        async def ainvoke(self, msgs):
            llm_calls.append(msgs)
            return AIMessage(
                content=(
                    "HNSW uses hierarchical layers [1] and [9] plus [G1] and [G9]. "
                    "Read [doc](https://example.com/1)."
                )
            )

    q_emb = [0.9, 0.1, 0.0, 0.0]
    await cg._EMBED_CACHE.set("Explain HNSW", q_emb)

    state = {
        "user_id": "u1",
        "intent": "explain",
        "entities": ["HNSW"],
        "retrieval_query": "Explain HNSW",
        "messages": [HumanMessage(content="Explain HNSW")],
        "graph_context": {
            "concepts": [{"id": "c-1", "name": "HNSW", "definition": "Graph ANN"}],
            "relationships": [],
        },
        "rag_context": [{
            "id": "ch1",
            "parent_chunk_id": "p1",
            "title": "HNSW Notes",
            "content": "HNSW builds navigable small world layers.",
            "similarity": 0.88,
            "_rrf_score": 0.04,
            "images": [],
        }],
    }

    fingerprint = {"value": "3.1700000000"}

    async def fake_fingerprint(_user_id):
        return fingerprint["value"]

    with patch.object(cg, "get_chat_model", return_value=FakeLLM()), \
         patch.object(cg, "_notes_fingerprint", side_effect=fake_fingerprint):
        # 1. First call: misses L2, calls LLM, strips [9] and [G9], preserves [1], [G1], and markdown link, caches.
        res1 = await cg.generate_response_node(state)
        assert len(llm_calls) == 1
        ans1 = res1["messages"][-1].content
        assert "[1]" in ans1
        assert "[G1]" in ans1
        assert "[9]" not in ans1
        assert "[G9]" not in ans1
        assert "[doc](https://example.com/1)" in ans1
        assert res1["metadata"]["cache_hit"] is False
        assert res1["metadata"]["grounding"]["should_abstain"] is False
        assert res1["metadata"]["grounding"]["invalid_refs"] == ["9", "G9"]

        # 2. Second identical single-turn call: L2 cache hit, zero extra LLM calls.
        res2 = await cg.generate_response_node(state)
        assert len(llm_calls) == 1
        assert res2["messages"][-1].content == ans1
        assert res2["metadata"]["cache_hit"] is True

        # 3. Multi-turn (len(messages) > 1) bypasses L2 cache.
        multi_state = dict(state)
        multi_state["messages"] = [
            HumanMessage(content="Hi"),
            AIMessage(content="Hello!"),
            HumanMessage(content="Explain HNSW"),
        ]
        res3 = await cg.generate_response_node(multi_state)
        assert len(llm_calls) == 2
        assert res3["metadata"]["cache_hit"] is False

        # 4. Bump user corpus version invalidates single-turn L2 cache.
        ver = await cg.bump_user_corpus_version("u1")
        assert ver == 1
        res4 = await cg.generate_response_node(state)
        assert len(llm_calls) == 3
        assert res4["metadata"]["cache_hit"] is False

        # 5. A note added or deleted anywhere (fingerprint changes) also invalidates: no stale sources.
        assert (await cg.generate_response_node(state))["metadata"]["cache_hit"] is True
        fingerprint["value"] = "2.1700000900"
        res5 = await cg.generate_response_node(state)
        assert len(llm_calls) == 4
        assert res5["metadata"]["cache_hit"] is False


@pytest.mark.asyncio
async def test_generate_response_low_confidence_abstention_notice_and_no_cache() -> None:
    captured_prompts: list[list] = []

    class FakeLLM:
        def with_config(self, cfg):
            return self

        async def ainvoke(self, msgs):
            captured_prompts.append(msgs)
            return AIMessage(content="I do not have enough information in your notes.")

    await cg._EMBED_CACHE.set("What is Quantum B-Tree?", [0.2, 0.8, 0.0, 0.0])

    low_conf_state = {
        "user_id": "u1",
        "intent": "find",
        "entities": [],
        "retrieval_query": "What is Quantum B-Tree?",
        "messages": [HumanMessage(content="What is Quantum B-Tree?")],
        "graph_context": {"concepts": [], "relationships": []},
        "rag_context": [{
            "id": "ch1",
            "parent_chunk_id": "p1",
            "title": "Unrelated",
            "content": "Cooking recipe notes.",
            "similarity": 0.25,
            "images": [],
        }],
    }

    with patch.object(cg, "get_chat_model", return_value=FakeLLM()):
        out1 = await cg.generate_response_node(low_conf_state)
        out2 = await cg.generate_response_node(low_conf_state)

    # Low-confidence abstained response must NOT be cached in L2, so LLM is called both times.
    assert len(captured_prompts) == 2
    assert isinstance(captured_prompts[0][0], SystemMessage)
    assert "<grounding_notice>" in captured_prompts[0][1].content
    assert out1["metadata"]["grounding"]["should_abstain"] is True
    assert out2["metadata"]["cache_hit"] is False
