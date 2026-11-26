"""Production RAG caching primitives: pluggable backends, embedding cache, and corpus-versioned response cache."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from collections import OrderedDict
from typing import Any, Callable, Optional, Protocol, Sequence, runtime_checkable

import structlog

logger = structlog.get_logger()

CACHEABLE_INTENTS: frozenset[str] = frozenset(
    {"explain", "compare", "find", "summarize", "show_images"}
)

# Common technical acronyms, model/algorithm names, and protocols that distinguish queries
# even when written in lowercase inside natural language.
_KNOWN_TECH_TOKENS: frozenset[str] = frozenset(
    {
        "l1",
        "l2",
        "l3",
        "lora",
        "qlora",
        "dora",
        "peft",
        "hnsw",
        "ivfflat",
        "ivfpq",
        "sm2",
        "fsrs",
        "bm25",
        "rrf",
        "tf",
        "idf",
        "tfidf",
        "rag",
        "hyde",
        "colbert",
        "splade",
        "pgvector",
        "faiss",
        "scann",
        "annoy",
        "neo4j",
        "postgres",
        "postgresql",
        "sqlite",
        "redis",
        "sql",
        "nosql",
        "orm",
        "api",
        "rest",
        "grpc",
        "graphql",
        "jwt",
        "oauth",
        "sso",
        "rbac",
        "abac",
        "acid",
        "cap",
        "mvcc",
        "wal",
        "btree",
        "lsm",
        "lru",
        "lfu",
        "ttl",
        "fifo",
        "dfs",
        "bfs",
        "dag",
        "cnn",
        "rnn",
        "lstm",
        "gru",
        "gan",
        "vae",
        "bert",
        "roberta",
        "gpt",
        "llama",
        "gemini",
        "claude",
        "llm",
        "nlp",
        "vlm",
        "moe",
        "mqa",
        "gqa",
        "mla",
        "rope",
        "alibi",
        "bpe",
        "relu",
        "gelu",
        "silu",
        "swiglu",
        "adam",
        "adamw",
        "sgd",
        "ppo",
        "dpo",
        "rlhf",
        "sft",
        "cpu",
        "gpu",
        "tpu",
        "cuda",
        "fp16",
        "bf16",
        "int8",
        "int4",
        "v1",
        "v2",
        "v3",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*")
_DIGIT_RE = re.compile(r"\d")


def normalize_query(query: str) -> str:
    """Normalize a query string by stripping, collapsing whitespace, and lowercasing."""
    return " ".join((query or "").strip().split()).lower()


def _content_terms(query: str) -> tuple[str, ...]:
    """Every topical word of the question, in order (framing words like "what is" dropped).
    Order matters: "GloVe improve on word2vec" and "word2vec improve on GloVe" share a set."""
    from backend.services.grounding_guard import query_terms

    return tuple(dict.fromkeys(_light_stem(t) for t in query_terms(query)))


def _light_stem(term: str) -> str:
    """Strip -ing/-ed/-s until stable, on both sides of the comparison ("indexing" == "index",
    "caches" == "cache"). Crude on purpose: a wrong stem can only cause a cache miss."""
    changed = True
    while changed:
        changed = False
        for suffix in ("ing", "ed", "s"):
            if len(term) > len(suffix) + 3 and term.endswith(suffix):
                term = term[: -len(suffix)]
                changed = True
                break
    return term


def extract_entity_tokens(query: str) -> frozenset[str]:
    """Extract distinguishing alphanumeric, numeric, acronym, and technical tokens.

    Preserves case sensitivity during inspection so CamelCase (e.g. ``LoRA``, ``IVFFlat``)
    and ALL-CAPS acronyms (e.g. ``HNSW``, ``FSRS``) are detected alongside numeric/version
    tokens (e.g. ``l1``, ``l2``, ``v1``, ``v2``, ``sm2``) and known technical identifiers.
    """
    if not query:
        return frozenset()

    entities: set[str] = set()
    for match in _TOKEN_RE.finditer(query):
        raw = match.group(0)
        lower = raw.lower()
        has_digit = bool(_DIGIT_RE.search(raw))
        is_all_caps = len(raw) >= 2 and raw.isalpha() and raw.isupper()
        is_camel_case = (
            len(raw) >= 2
            and any(ch.isupper() for ch in raw[1:])
            and any(ch.islower() for ch in raw)
        )
        has_compound_sep = any(sep in raw for sep in ("_", ".")) or (
            "-" in raw and any(ch.isdigit() for ch in raw)
        )

        if (
            has_digit
            or is_all_caps
            or is_camel_case
            or has_compound_sep
            or lower in _KNOWN_TECH_TOKENS
        ):
            entities.add(lower)

    return frozenset(entities)


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute cosine similarity between two equal-length float vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        norm_a += fx * fx
        norm_b += fy * fy
    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    if denom <= 0.0:
        return 0.0
    return dot / denom


@runtime_checkable
class CacheBackend(Protocol):
    """Pluggable async string key-value cache protocol."""

    async def get(self, key: str) -> Optional[str]:
        ...

    async def set(self, key: str, value: str, ttl_s: Optional[int] = None) -> None:
        ...

    async def delete(self, key: str) -> None:
        ...

    async def incr(self, key: str, amount: int = 1, ttl_s: Optional[int] = None) -> int:
        ...


class InMemoryTTLCache:
    """Async-safe OrderedDict LRU cache with monotonic TTL expiration."""

    def __init__(
        self,
        max_entries: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_entries = max(0, int(max_entries))
        self._clock = clock
        self._lock = asyncio.Lock()
        self._store: OrderedDict[str, tuple[str, Optional[float]]] = OrderedDict()

    def _purge_expired_locked(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._store.items() if exp is not None and now >= exp]
        for key in expired:
            del self._store[key]

    def _evict_if_needed_locked(self, now: float) -> None:
        if self._max_entries <= 0:
            self._store.clear()
            return
        if len(self._store) >= self._max_entries:
            self._purge_expired_locked(now)
        while len(self._store) >= self._max_entries:
            self._store.popitem(last=False)

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at is not None and self._clock() >= expires_at:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    async def set(self, key: str, value: str, ttl_s: Optional[int] = None) -> None:
        async with self._lock:
            if self._max_entries <= 0:
                return
            if ttl_s is not None and ttl_s <= 0:
                self._store.pop(key, None)
                return
            now = self._clock()
            expires_at = (now + float(ttl_s)) if ttl_s is not None else None
            if key in self._store:
                self._store[key] = (value, expires_at)
                self._store.move_to_end(key)
                return
            self._evict_if_needed_locked(now)
            self._store[key] = (value, expires_at)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def incr(self, key: str, amount: int = 1, ttl_s: Optional[int] = None) -> int:
        async with self._lock:
            now = self._clock()
            entry = self._store.get(key)
            current = 0
            existing_exp: Optional[float] = None
            if entry is not None:
                raw_val, exp = entry
                if exp is not None and now >= exp:
                    del self._store[key]
                else:
                    current = int(raw_val)
                    existing_exp = exp

            new_val = current + int(amount)
            if ttl_s is not None:
                if ttl_s <= 0:
                    self._store.pop(key, None)
                    return new_val
                new_exp: Optional[float] = now + float(ttl_s)
            else:
                new_exp = existing_exp

            if self._max_entries > 0:
                if key not in self._store:
                    self._evict_if_needed_locked(now)
                self._store[key] = (str(new_val), new_exp)
                self._store.move_to_end(key)
            return new_val


class RedisCacheBackend:
    """Gracefully-degrading async Redis CacheBackend with lazy redis.asyncio import."""

    def __init__(self, url: str, socket_timeout_s: float = 0.5) -> None:
        self._url = url
        self._socket_timeout_s = float(socket_timeout_s)
        self._client: Any = None
        self.degraded_errors: int = 0

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from redis import asyncio as aioredis  # lazy optional import

        self._client = aioredis.from_url(
            self._url,
            socket_timeout=self._socket_timeout_s,
            socket_connect_timeout=self._socket_timeout_s,
            decode_responses=True,
        )
        return self._client

    def _record_degraded(self, op: str, exc: Exception) -> None:
        self.degraded_errors += 1
        logger.warning("RedisCacheBackend degraded", op=op, error=str(exc))

    async def get(self, key: str) -> Optional[str]:
        try:
            client = self._get_client()
            val = await client.get(key)
            if val is None:
                return None
            return val.decode("utf-8") if isinstance(val, bytes) else str(val)
        except Exception as exc:
            self._record_degraded("get", exc)
            return None

    async def set(self, key: str, value: str, ttl_s: Optional[int] = None) -> None:
        try:
            client = self._get_client()
            if ttl_s is not None:
                if ttl_s <= 0:
                    await client.delete(key)
                    return
                await client.set(key, value, ex=int(ttl_s))
            else:
                await client.set(key, value)
        except Exception as exc:
            self._record_degraded("set", exc)

    async def delete(self, key: str) -> None:
        try:
            client = self._get_client()
            await client.delete(key)
        except Exception as exc:
            self._record_degraded("delete", exc)

    async def incr(self, key: str, amount: int = 1, ttl_s: Optional[int] = None) -> int:
        try:
            client = self._get_client()
            val = await client.incr(key, amount)
            if ttl_s is not None and ttl_s > 0:
                await client.expire(key, int(ttl_s))
            return int(val)
        except Exception as exc:
            self._record_degraded("incr", exc)
            return 0


class EmbeddingCache:
    """Normalized-query embedding vector cache keyed by (model_tag, sha256(norm_query))."""

    def __init__(
        self,
        backend: CacheBackend,
        ttl_s: int = 3600,
        model_tag: str = "default",
    ) -> None:
        self._backend = backend
        self._ttl_s = int(ttl_s)
        self._model_tag = model_tag or "default"
        self._hits = 0
        self._misses = 0

    @staticmethod
    def normalize_query(q: str) -> str:
        """Normalize query whitespace and casing for stable embedding cache keys."""
        return normalize_query(q)

    def _make_key(self, query: str) -> str:
        norm = self.normalize_query(query)
        digest = hashlib.sha256(
            f"{self._model_tag}\x00{norm}".encode("utf-8")
        ).hexdigest()
        return f"rag:emb:{self._model_tag}:{digest}"

    async def get(self, query: str) -> Optional[list[float]]:
        key = self._make_key(query)
        raw = await self._backend.get(key)
        if raw is None:
            self._misses += 1
            return None
        try:
            decoded = json.loads(raw)
            if not isinstance(decoded, list):
                self._misses += 1
                return None
            vec = [float(x) for x in decoded]
        except Exception:
            self._misses += 1
            return None
        self._hits += 1
        return vec

    async def set(self, query: str, embedding: Sequence[float]) -> None:
        key = self._make_key(query)
        payload = json.dumps([float(x) for x in embedding])
        await self._backend.set(key, payload, ttl_s=self._ttl_s)

    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        hit_rate = (self._hits / total) if total > 0 else 0.0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 6),
        }


class CorpusVersionedResponseCache:
    """Tenant-, corpus-version-, and intent-partitioned exact + semantic RAG response cache."""

    CACHEABLE_INTENTS: frozenset[str] = CACHEABLE_INTENTS

    def __init__(
        self,
        backend: CacheBackend,
        ttl_s: int = 900,
        # Measured with gemini-embedding-001 @768 (Nov 2026): real paraphrases 0.86-0.96, one-entity
        # swaps 0.63-0.84 (BFS/DFS 0.75, MQA/GQA 0.84). The content-term guard below blocks swaps
        # regardless of cosine, so the threshold only has to admit paraphrases.
        semantic_threshold: float = 0.92,
        max_semantic_entries_per_tenant: int = 64,
    ) -> None:
        self._backend = backend
        self._ttl_s = int(ttl_s)
        self._semantic_threshold = float(semantic_threshold)
        self._max_semantic_entries_per_tenant = max(1, int(max_semantic_entries_per_tenant))
        self._sem_lock = asyncio.Lock()

        self._exact_hits = 0
        self._semantic_hits = 0
        self._misses = 0
        self._entity_guard_blocks = 0
        self._skipped_intents = 0

    @staticmethod
    def _version_key(user_id: str) -> str:
        return f"rag:cv:{user_id}"

    @staticmethod
    def _exact_key(user_id: str, version: int, intent: str, norm_query: str) -> str:
        digest = hashlib.sha256(norm_query.encode("utf-8")).hexdigest()
        return f"rag:resp:exact:{user_id}:v{version}:{intent}:{digest}"

    @staticmethod
    def _semantic_key(user_id: str, version: int, intent: str) -> str:
        return f"rag:resp:sem:{user_id}:v{version}:{intent}"

    async def get_corpus_version(self, user_id: str) -> int:
        raw = await self._backend.get(self._version_key(user_id))
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def bump_corpus_version(self, user_id: str) -> int:
        return await self._backend.incr(self._version_key(user_id), amount=1)

    def _is_cacheable_intent(self, intent: str) -> bool:
        return (intent or "").strip().lower() in self.CACHEABLE_INTENTS

    async def get(
        self,
        user_id: str,
        query: str,
        intent: str,
        query_embedding: Optional[Sequence[float]] = None,
    ) -> Optional[Any]:
        norm_intent = (intent or "").strip().lower()
        if not self._is_cacheable_intent(norm_intent):
            self._skipped_intents += 1
            return None

        version = await self.get_corpus_version(user_id)
        norm_q = normalize_query(query)
        exact_key = self._exact_key(user_id, version, norm_intent, norm_q)

        exact_raw = await self._backend.get(exact_key)
        if exact_raw is not None:
            try:
                decoded = json.loads(exact_raw)
                if isinstance(decoded, dict) and "response" in decoded:
                    self._exact_hits += 1
                    return decoded["response"]
            except Exception:
                pass

        if query_embedding:
            sem_key = self._semantic_key(user_id, version, norm_intent)
            sem_raw = await self._backend.get(sem_key)
            if sem_raw is not None:
                try:
                    entries = json.loads(sem_raw)
                except Exception:
                    entries = []
                if isinstance(entries, list) and entries:
                    query_terms_seq = _content_terms(query)
                    scored: list[tuple[float, dict[str, Any]]] = []
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        emb = entry.get("embedding")
                        if not isinstance(emb, list) or not emb:
                            continue
                        sim = _cosine_similarity(query_embedding, emb)
                        if sim >= self._semantic_threshold:
                            scored.append((sim, entry))

                    scored.sort(key=lambda item: item[0], reverse=True)
                    for _, entry in scored:
                        # Same topic words in the same order or no hit: "precision" vs "recall",
                        # "GPT-3" vs "GPT-4", "use" vs "not use" and swapped comparisons all differ
                        # here even when the embeddings are close. Entries without content_terms
                        # (written before this guard) never match.
                        cached_terms = entry.get("content_terms")
                        if cached_terms is None or tuple(cached_terms) != query_terms_seq:
                            self._entity_guard_blocks += 1
                            continue
                        if "response" in entry:
                            self._semantic_hits += 1
                            return entry["response"]

        self._misses += 1
        return None

    async def set(
        self,
        user_id: str,
        query: str,
        intent: str,
        response: Any,
        query_embedding: Optional[Sequence[float]] = None,
    ) -> bool:
        norm_intent = (intent or "").strip().lower()
        if not self._is_cacheable_intent(norm_intent):
            self._skipped_intents += 1
            return False

        version = await self.get_corpus_version(user_id)
        norm_q = normalize_query(query)
        exact_key = self._exact_key(user_id, version, norm_intent, norm_q)
        exact_payload = json.dumps({"query": norm_q, "response": response})
        await self._backend.set(exact_key, exact_payload, ttl_s=self._ttl_s)

        if query_embedding:
            sem_key = self._semantic_key(user_id, version, norm_intent)
            new_entry = {
                "norm_query": norm_q,
                "entity_tokens": sorted(extract_entity_tokens(query)),
                "content_terms": list(_content_terms(query)),
                "embedding": [float(x) for x in query_embedding],
                "response": response,
            }
            async with self._sem_lock:
                existing_raw = await self._backend.get(sem_key)
                entries: list[dict[str, Any]] = []
                if existing_raw is not None:
                    try:
                        parsed = json.loads(existing_raw)
                        if isinstance(parsed, list):
                            entries = [
                                e
                                for e in parsed
                                if isinstance(e, dict) and e.get("norm_query") != norm_q
                            ]
                    except Exception:
                        entries = []
                entries.append(new_entry)
                if len(entries) > self._max_semantic_entries_per_tenant:
                    entries = entries[-self._max_semantic_entries_per_tenant :]
                await self._backend.set(sem_key, json.dumps(entries), ttl_s=self._ttl_s)

        return True

    def stats(self) -> dict[str, int]:
        return {
            "exact_hits": self._exact_hits,
            "semantic_hits": self._semantic_hits,
            "hits": self._exact_hits + self._semantic_hits,
            "misses": self._misses,
            "entity_guard_blocks": self._entity_guard_blocks,
            "skipped_intents": self._skipped_intents,
        }
