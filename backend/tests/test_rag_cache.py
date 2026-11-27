"""Pure unit tests for backend.services.rag_cache."""

from __future__ import annotations

import asyncio
import builtins
import sys
import types
from unittest.mock import AsyncMock

import pytest

from backend.services.rag_cache import (
    CACHEABLE_INTENTS,
    CacheBackend,
    CorpusVersionedResponseCache,
    EmbeddingCache,
    InMemoryTTLCache,
    RedisCacheBackend,
    extract_entity_tokens,
)


class _FakeClock:
    def __init__(self, initial: float = 100.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# InMemoryTTLCache
# ---------------------------------------------------------------------------


def test_in_memory_cache_satisfies_protocol_and_crud() -> None:
    cache = InMemoryTTLCache(max_entries=16)
    assert isinstance(cache, CacheBackend)

    async def scenario() -> None:
        assert await cache.get("missing") is None
        await cache.set("k1", "v1", ttl_s=60)
        assert await cache.get("k1") == "v1"
        await cache.delete("k1")
        assert await cache.get("k1") is None

    asyncio.run(scenario())


def test_in_memory_cache_lru_eviction_respects_recency() -> None:
    cache = InMemoryTTLCache(max_entries=2)

    async def scenario() -> None:
        await cache.set("a", "1")
        await cache.set("b", "2")
        # Touch 'a' so 'b' becomes the least-recently-used key.
        assert await cache.get("a") == "1"
        await cache.set("c", "3")

        assert await cache.get("a") == "1"
        assert await cache.get("b") is None
        assert await cache.get("c") == "3"

    asyncio.run(scenario())


def test_in_memory_cache_ttl_expiration_and_incr() -> None:
    clock = _FakeClock(10.0)
    cache = InMemoryTTLCache(max_entries=8, clock=clock)

    async def scenario() -> None:
        await cache.set("temp", "hello", ttl_s=5)
        assert await cache.get("temp") == "hello"
        clock.advance(4.9)
        assert await cache.get("temp") == "hello"
        clock.advance(0.2)
        assert await cache.get("temp") is None

        assert await cache.incr("counter") == 1
        assert await cache.incr("counter", amount=4) == 5
        assert await cache.get("counter") == "5"

        assert await cache.incr("exp_counter", amount=2, ttl_s=3) == 2
        clock.advance(3.1)
        assert await cache.incr("exp_counter", amount=1) == 1

    asyncio.run(scenario())


def test_in_memory_cache_concurrent_incr_is_atomic() -> None:
    cache = InMemoryTTLCache(max_entries=16)

    async def scenario() -> None:
        results = await asyncio.gather(*(cache.incr("shared") for _ in range(50)))
        assert sorted(results) == list(range(1, 51))
        assert await cache.get("shared") == "50"

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# RedisCacheBackend graceful degradation
# ---------------------------------------------------------------------------


def test_redis_cache_backend_gracefully_degrades_when_package_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orig_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "redis" or name.startswith("redis."):
            raise ImportError("No module named 'redis'")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "redis", raising=False)
    monkeypatch.delitem(sys.modules, "redis.asyncio", raising=False)

    backend = RedisCacheBackend("redis://localhost:6379/0", socket_timeout_s=0.2)

    async def scenario() -> None:
        assert await backend.get("k1") is None
        await backend.set("k1", "v1", ttl_s=10)
        await backend.delete("k1")
        assert await backend.incr("counter") == 0

    asyncio.run(scenario())
    assert backend.degraded_errors == 4


def test_redis_cache_backend_gracefully_degrades_on_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = types.SimpleNamespace(
        get=AsyncMock(side_effect=ConnectionError("connection refused")),
        set=AsyncMock(side_effect=TimeoutError("timed out")),
        delete=AsyncMock(side_effect=ConnectionError("connection refused")),
        incr=AsyncMock(side_effect=ConnectionError("connection refused")),
        expire=AsyncMock(),
    )
    fake_aioredis = types.SimpleNamespace(from_url=lambda *a, **kw: fake_client)
    fake_redis_pkg = types.ModuleType("redis")
    fake_redis_pkg.asyncio = fake_aioredis  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "redis", fake_redis_pkg)
    monkeypatch.setitem(sys.modules, "redis.asyncio", fake_aioredis)

    backend = RedisCacheBackend("redis://localhost:6379/0", socket_timeout_s=0.1)

    async def scenario() -> None:
        assert await backend.get("k") is None
        await backend.set("k", "v", ttl_s=30)
        await backend.delete("k")
        assert await backend.incr("c", amount=2, ttl_s=30) == 0

    asyncio.run(scenario())
    assert backend.degraded_errors == 4


def test_redis_cache_backend_happy_path_with_mock_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = types.SimpleNamespace(
        get=AsyncMock(return_value="cached-value"),
        set=AsyncMock(return_value=True),
        delete=AsyncMock(return_value=1),
        incr=AsyncMock(return_value=3),
        expire=AsyncMock(return_value=True),
    )
    fake_aioredis = types.SimpleNamespace(from_url=lambda *a, **kw: fake_client)
    fake_redis_pkg = types.ModuleType("redis")
    fake_redis_pkg.asyncio = fake_aioredis  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "redis", fake_redis_pkg)
    monkeypatch.setitem(sys.modules, "redis.asyncio", fake_aioredis)

    backend = RedisCacheBackend("redis://localhost:6379/0", socket_timeout_s=0.5)

    async def scenario() -> None:
        await backend.set("k", "cached-value", ttl_s=120)
        assert await backend.get("k") == "cached-value"
        assert await backend.incr("v", amount=1, ttl_s=60) == 3
        await backend.delete("k")

    asyncio.run(scenario())
    assert backend.degraded_errors == 0
    fake_client.set.assert_awaited_once_with("k", "cached-value", ex=120)
    fake_client.expire.assert_awaited_once_with("v", 60)


# ---------------------------------------------------------------------------
# EmbeddingCache
# ---------------------------------------------------------------------------


def test_embedding_cache_normalization_model_isolation_and_stats() -> None:
    backend = InMemoryTTLCache()
    emb_v1 = EmbeddingCache(backend, ttl_s=3600, model_tag="text-emb-v1")
    emb_v2 = EmbeddingCache(backend, ttl_s=3600, model_tag="text-emb-v2")

    assert EmbeddingCache.normalize_query("  What   is   HNSW? ") == "what is hnsw?"

    async def scenario() -> None:
        assert await emb_v1.get("What is HNSW?") is None
        await emb_v1.set("What is HNSW?", [0.1, 0.2, 0.3])

        # Whitespace and case variants normalize to the same key.
        assert await emb_v1.get("  what   is   hnsw?  ") == [0.1, 0.2, 0.3]
        # Different model_tag must NOT collide.
        assert await emb_v2.get("What is HNSW?") is None

    asyncio.run(scenario())
    stats = emb_v1.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


# ---------------------------------------------------------------------------
# CorpusVersionedResponseCache
# ---------------------------------------------------------------------------


def test_response_cache_exact_hit_and_tenant_intent_partitioning() -> None:
    backend = InMemoryTTLCache()
    cache = CorpusVersionedResponseCache(backend, ttl_s=900)

    assert CACHEABLE_INTENTS == frozenset({"explain", "compare", "find", "summarize", "show_images"})

    async def scenario() -> None:
        await cache.set("user-1", "What is HNSW?", "explain", {"answer": "HNSW is a graph index."})
        # Exact normalized hit for same tenant & intent.
        hit = await cache.get("user-1", "  what  is  hnsw? ", "explain")
        assert hit == {"answer": "HNSW is a graph index."}

        # Different tenant must miss.
        assert await cache.get("user-2", "What is HNSW?", "explain") is None
        # Different intent must miss.
        assert await cache.get("user-1", "What is HNSW?", "compare") is None

    asyncio.run(scenario())
    stats = cache.stats()
    assert stats["exact_hits"] == 1
    assert stats["misses"] == 2


def test_response_cache_refuses_non_cacheable_intents() -> None:
    backend = InMemoryTTLCache()
    cache = CorpusVersionedResponseCache(backend)

    async def scenario() -> None:
        for intent in ("quiz", "general", "path"):
            stored = await cache.set("user-1", "test query", intent, {"answer": "nope"})
            assert stored is False
            assert await cache.get("user-1", "test query", intent) is None

    asyncio.run(scenario())
    stats = cache.stats()
    assert stats["skipped_intents"] == 6
    assert stats["exact_hits"] == 0
    assert stats["semantic_hits"] == 0


def test_response_cache_corpus_version_bump_invalidates_exact_and_semantic() -> None:
    backend = InMemoryTTLCache()
    cache = CorpusVersionedResponseCache(backend, semantic_threshold=0.95)
    emb = [1.0, 0.0, 0.0]

    async def scenario() -> None:
        assert await cache.get_corpus_version("user-1") == 0
        await cache.set("user-1", "Explain gradient descent", "explain", {"answer": "v0"}, query_embedding=emb)
        assert await cache.get("user-1", "How does gradient descent work?", "explain", query_embedding=[0.99, 0.05, 0.0]) == {"answer": "v0"}

        new_ver = await cache.bump_corpus_version("user-1")
        assert new_ver == 1
        assert await cache.get_corpus_version("user-1") == 1

        # Both exact and semantic lookups must miss after corpus version bump.
        assert await cache.get("user-1", "Explain gradient descent", "explain") is None
        assert await cache.get("user-1", "How does gradient descent work?", "explain", query_embedding=[0.99, 0.05, 0.0]) is None
        # Other tenant's corpus version remains untouched.
        assert await cache.get_corpus_version("user-2") == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("cached_query", "candidate_query"),
    [
        ("Explain L1 regularization", "Explain L2 regularization"),
        ("What is lora fine-tuning?", "What is qlora fine-tuning?"),
        ("How does hnsw work?", "How does ivfflat work?"),
        ("Compare sm2 scheduling", "Compare fsrs scheduling"),
        ("Migration guide for v1 API", "Migration guide for v2 API"),
    ],
)
def test_response_cache_entity_token_guard_blocks_false_semantic_hits(
    cached_query: str,
    candidate_query: str,
) -> None:
    backend = InMemoryTTLCache()
    cache = CorpusVersionedResponseCache(backend, semantic_threshold=0.95)
    # Identical embeddings (cosine = 1.0) to prove entity guard stops the false hit.
    identical_emb = [0.6, 0.8, 0.0]

    async def scenario() -> None:
        await cache.set("user-1", cached_query, "explain", {"answer": "cached"}, query_embedding=identical_emb)
        res = await cache.get("user-1", candidate_query, "explain", query_embedding=identical_emb)
        assert res is None

    asyncio.run(scenario())
    stats = cache.stats()
    assert stats["entity_guard_blocks"] == 1
    assert stats["semantic_hits"] == 0
    assert stats["misses"] == 1


def test_response_cache_entity_guard_allows_matching_entity_paraphrase_and_caps_entries() -> None:
    backend = InMemoryTTLCache()
    cache = CorpusVersionedResponseCache(
        backend,
        semantic_threshold=0.96,
        max_semantic_entries_per_tenant=2,
    )

    assert "l1" in extract_entity_tokens("Explain L1 regularization")
    assert "ivfflat" in extract_entity_tokens("How does IVFFlat work?")

    async def scenario() -> None:
        await cache.set("user-1", "What is HNSW indexing?", "explain", {"ans": "hnsw"}, query_embedding=[1.0, 0.0, 0.0])
        # Paraphrase preserving the same entity token ('hnsw') should hit semantically.
        hit = await cache.get(
            "user-1",
            "Explain hnsw index",
            "explain",
            query_embedding=[0.99, 0.1, 0.0],
        )
        assert hit == {"ans": "hnsw"}

        # Insert two more distinct queries so max_semantic_entries_per_tenant=2 evicts the first.
        await cache.set("user-1", "Topic two", "explain", {"ans": "2"}, query_embedding=[0.0, 1.0, 0.0])
        await cache.set("user-1", "Topic three", "explain", {"ans": "3"}, query_embedding=[0.0, 0.0, 1.0])

        # First query's semantic entry is evicted, while exact entry is separate; semantic paraphrase misses.
        miss = await cache.get(
            "user-1",
            "Tell me about hnsw index",
            "explain",
            query_embedding=[0.99, 0.1, 0.0],
        )
        assert miss is None

    asyncio.run(scenario())
    assert cache.stats()["semantic_hits"] == 1


def test_response_cache_blocks_topic_swaps_even_when_embeddings_are_close() -> None:
    """The old guard compared only entity-looking tokens (digits, CAPS, CamelCase), so
    "precision" vs "recall" (both empty) slipped through on cosine alone."""
    cache = CorpusVersionedResponseCache(InMemoryTTLCache(), semantic_threshold=0.92)
    near = [0.999, 0.04, 0.0]

    async def scenario() -> None:
        await cache.set("u", "What is precision?", "explain", {"ans": "precision"}, query_embedding=[1.0, 0.0, 0.0])
        await cache.set("u", "Time complexity of quicksort", "explain", {"ans": "qs"}, query_embedding=[0.0, 1.0, 0.0])
        assert await cache.get("u", "What is recall?", "explain", query_embedding=near) is None
        assert await cache.get("u", "Time complexity of mergesort", "explain", query_embedding=[0.04, 0.999, 0.0]) is None
        # Same topic words, different framing and inflection: a semantic hit.
        assert await cache.get("u", "Explain precision", "explain", query_embedding=near) == {"ans": "precision"}
        # Same words, reversed comparison (measured 0.929 for GRU/LSTM, above the 0.92 bar): a miss.
        await cache.set("u", "How does GloVe improve on word2vec?", "compare", {"ans": "glove>w2v"},
                        query_embedding=[0.0, 0.0, 1.0])
        assert await cache.get("u", "How does word2vec improve on GloVe?", "compare",
                               query_embedding=[0.0, 0.03, 0.999]) is None

    asyncio.run(scenario())
    assert cache.stats()["entity_guard_blocks"] == 3


def test_question_word_is_part_of_the_semantic_cache_guard():
    from backend.services.rag_cache import _content_terms

    assert _content_terms("why does HNSW work?") != _content_terms("how does HNSW work?")
    assert _content_terms("How does HNSW work?") == _content_terms("Explain HNSW work")
    assert _content_terms("When was HNSW introduced?") != _content_terms("Where was HNSW introduced?")
    assert _content_terms("what is HNSW") == _content_terms("What is HNSW?")
