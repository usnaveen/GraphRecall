import asyncio
import hashlib
import os
import re
from typing import List, Optional, Tuple
import structlog
from backend.config.llm import get_embeddings, get_embedding_dims
from backend.services.grounding_guard import (
    AsyncCircuitBreaker,
    CircuitBreakerOpenError,
    is_retryable_llm_error,
)

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
CACHE_ENABLED = os.getenv("EMBEDDING_CACHE", "1") != "0"

_PAYLOAD_BATCH_ERROR_MARKERS: tuple[str, ...] = (
    "payload",
    "batch size",
    "batch_size",
    "too large",
    "request size",
    "size limit",
    "too many tokens",
    "token limit",
    "max_tokens",
    "content too long",
    "413",
)


def _model_name(embedder) -> str:
    return str(getattr(embedder, "model", None) or getattr(embedder, "model_name", None) or "embedding")


def cache_key(model: str, dims: int, text: str) -> str:
    return hashlib.sha256(f"{model}|{dims}|{text}".encode("utf-8")).hexdigest()


def _is_payload_batch_error(exc: BaseException) -> bool:
    """Return True only when an error indicates request payload/batch-size overflow."""
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int) and val == 413:
            return True
    response = getattr(exc, "response", None)
    if response is not None:
        val = getattr(response, "status_code", None)
        if isinstance(val, int) and val == 413:
            return True
    msg = str(exc).lower()
    return any(marker in msg for marker in _PAYLOAD_BATCH_ERROR_MARKERS)


def _dedupe_texts(texts: List[str]) -> Tuple[List[str], List[int]]:
    """Deduplicate texts preserving first-seen order and returning index mapping."""
    unique_texts: List[str] = []
    text_to_uidx: dict[str, int] = {}
    idx_map: List[int] = []
    for t in texts:
        uidx = text_to_uidx.get(t)
        if uidx is None:
            uidx = len(unique_texts)
            text_to_uidx[t] = uidx
            unique_texts.append(t)
        idx_map.append(uidx)
    return unique_texts, idx_map


logger = structlog.get_logger()

MAX_RETRIES = 3
MAX_BATCH_SIZE = 50


class EmbeddingService:
    """
    Service for generating vector embeddings for document chunks.

    Uses gemini-embedding-001 via centralized config (config/llm.py).
    Produces 768-dimensional vectors (MRL-trained, 99.74% quality of 3072).
    """

    def __init__(self):
        self.embedder = get_embeddings()
        self.dims = get_embedding_dims()
        self._circuit_breaker = AsyncCircuitBreaker()

    def _get_circuit_breaker(self) -> AsyncCircuitBreaker:
        cb = getattr(self, "_circuit_breaker", None)
        if cb is None:
            cb = AsyncCircuitBreaker()
            self._circuit_breaker = cb
        return cb

    async def _embed_with_retry_result(
        self, texts: List[str]
    ) -> Tuple[List[List[float]], Optional[BaseException]]:
        """Embed a small batch with exponential backoff on retryable errors only."""
        cb = self._get_circuit_breaker()
        last_exc: Optional[BaseException] = None
        for attempt in range(MAX_RETRIES):
            try:
                embeddings = await cb.call(
                    self.embedder.aembed_documents,
                    texts,
                    output_dimensionality=self.dims,
                )
                return embeddings, None
            except CircuitBreakerOpenError as e:
                logger.warning(
                    "Embedding circuit breaker open, failing fast",
                    retry_after_s=e.retry_after_s,
                    batch_size=len(texts),
                )
                return [], e
            except Exception as e:
                last_exc = e
                if not is_retryable_llm_error(e):
                    logger.error(
                        "Embedding failed with non-retryable error, failing fast",
                        error=str(e),
                        batch_size=len(texts),
                    )
                    return [], e
                wait = 2 ** attempt
                logger.warning(
                    "Embedding attempt failed, retrying",
                    attempt=attempt + 1,
                    max_retries=MAX_RETRIES,
                    wait_seconds=wait,
                    error=str(e),
                    batch_size=len(texts),
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(wait)
        return [], last_exc

    async def _embed_with_retry(self, texts: List[str]) -> List[List[float]]:
        """Embed a small batch with exponential backoff retry."""
        embeddings, _ = await self._embed_with_retry_result(texts)
        return embeddings

    async def _write_cache_batch(
        self,
        pg,
        *,
        owner: str,
        model: str,
        items: List[Tuple[str, List[float]]],
    ) -> None:
        """Persist cache misses in a single DB session/transaction where supported."""
        if not items:
            return
        if callable(getattr(pg, "session", None)):
            from sqlalchemy import text

            async with pg.session() as session:
                for start in range(0, len(items), 500):
                    chunk = items[start : start + 500]
                    values_sql: List[str] = []
                    params: dict[str, object] = {"u": owner, "m": model, "d": self.dims}
                    for idx, (k, vec) in enumerate(chunk):
                        values_sql.append(f"(:k_{idx}, CAST(:u AS uuid), :m, :d, :e_{idx})")
                        params[f"k_{idx}"] = k
                        params[f"e_{idx}"] = [float(x) for x in vec]
                    sql = (
                        "INSERT INTO embedding_cache (key, user_id, model, dims, embedding) VALUES "
                        + ", ".join(values_sql)
                        + " ON CONFLICT DO NOTHING"
                    )
                    await session.execute(text(sql), params)
            return

        for k, vec in items:
            await pg.execute_update(
                "INSERT INTO embedding_cache (key, user_id, model, dims, embedding) "
                "VALUES (:k, CAST(:u AS uuid), :m, :d, :e) ON CONFLICT DO NOTHING",
                {"k": k, "u": owner, "m": model, "d": self.dims, "e": [float(x) for x in vec]},
            )

    async def embed_batch(self, texts: List[str], owner: Optional[str] = None) -> List[List[float]]:
        """Embed a batch of texts for storage (retrieval_document task).

        With ``owner`` (a user id), vectors already computed for the same text, model and dims
        come from the per-user embedding cache; only the misses hit the API.
        """
        if not texts:
            return []

        if not owner or not CACHE_ENABLED or not _UUID.match(str(owner)):
            unique_texts, idx_map = _dedupe_texts(texts)
            unique_vecs = await self._embed_uncached(unique_texts)
            if not unique_vecs:
                return []
            return [unique_vecs[u] if u < len(unique_vecs) else [] for u in idx_map]

        model = _model_name(self.embedder)
        keys = [cache_key(model, self.dims, t) for t in texts]
        hits: dict[str, List[float]] = {}
        try:
            from backend.db.postgres_client import get_postgres_client

            pg = await get_postgres_client()
            rows = await pg.execute_query(
                "SELECT key, embedding FROM embedding_cache WHERE user_id = CAST(:u AS uuid) AND key = ANY(:keys)",
                {"u": owner, "keys": list(set(keys))},
            )
            hits = {r["key"]: list(r["embedding"]) for r in rows or []}
        except Exception as e:  # noqa: BLE001 - the cache is an optimisation
            logger.warning("embedding cache read failed", error=str(e)[:200])
            pg = None

        missing_keys: List[str] = []
        missing_texts: List[str] = []
        seen_missing: set[str] = set()
        for t, k in zip(texts, keys):
            if k not in hits and k not in seen_missing:
                seen_missing.add(k)
                missing_keys.append(k)
                missing_texts.append(t)

        fresh = await self._embed_uncached(missing_texts) if missing_texts else []
        fresh_by_key = {k: vec for k, vec in zip(missing_keys, fresh) if vec}
        out: List[List[float]] = [
            hits[k] if k in hits else fresh_by_key.get(k, [])
            for k in keys
        ]
        hit_count = sum(1 for k in keys if k in hits)
        logger.info("embed_batch: cache", total=len(texts), hits=hit_count, unique_misses=len(missing_texts))
        if pg is not None and missing_keys:
            to_write = [(k, fresh_by_key[k]) for k in missing_keys if k in fresh_by_key]
            if to_write:
                try:
                    await self._write_cache_batch(pg, owner=owner, model=model, items=to_write)
                except Exception as e:  # noqa: BLE001
                    logger.warning("embedding cache write failed", error=str(e)[:200])
        return out

    async def _embed_uncached(self, texts: List[str]) -> List[List[float]]:
        """Embed via the API: splits large batches and retries on transient failures."""
        if not self.embedder:
            logger.error("Embedding service not configured")
            return []

        if not texts:
            return []

        # Split into smaller batches to avoid API limits
        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), MAX_BATCH_SIZE):
            batch = texts[i:i + MAX_BATCH_SIZE]
            batch_embeddings, last_exc = await self._embed_with_retry_result(batch)

            if batch_embeddings:
                all_embeddings.extend(batch_embeddings)
                continue

            if isinstance(last_exc, CircuitBreakerOpenError):
                remaining = len(texts) - len(all_embeddings)
                all_embeddings.extend([[] for _ in range(remaining)])
                break

            if len(batch) > 1 and last_exc is not None and _is_payload_batch_error(last_exc):
                # Only fall back to 1-by-1 on payload/batch-size overflow, never on 429 or auth/bad-request errors.
                logger.warning(
                    "Batch embedding hit payload/size limit, falling back to individual embedding",
                    batch_start=i,
                    batch_size=len(batch),
                )
                aborted_by_breaker = False
                for j, text in enumerate(batch):
                    if aborted_by_breaker:
                        all_embeddings.append([])
                        continue
                    single, single_exc = await self._embed_with_retry_result([text])
                    if single:
                        all_embeddings.append(single[0])
                    else:
                        logger.error(
                            "Individual embedding failed permanently",
                            text_index=i + j,
                            text_preview=text[:80],
                        )
                        all_embeddings.append([])  # Placeholder - will be caught downstream
                        if isinstance(single_exc, CircuitBreakerOpenError):
                            aborted_by_breaker = True
                if aborted_by_breaker:
                    remaining = len(texts) - len(all_embeddings)
                    if remaining > 0:
                        all_embeddings.extend([[] for _ in range(remaining)])
                    break
            else:
                all_embeddings.extend([[] for _ in batch])

        success = sum(1 for e in all_embeddings if e)
        logger.info(
            "embed_batch: Complete",
            total=len(texts),
            success=success,
            failed=len(texts) - success,
        )
        return all_embeddings

    async def embed_query(self, text: str) -> List[float]:
        """Embed a search query for retrieval."""
        if not self.embedder:
            return []

        cb = self._get_circuit_breaker()
        for attempt in range(MAX_RETRIES):
            try:
                return await cb.call(
                    self.embedder.aembed_query,
                    text,
                    output_dimensionality=self.dims,
                )
            except CircuitBreakerOpenError as e:
                logger.warning("Query embedding circuit breaker open", retry_after_s=e.retry_after_s)
                return []
            except Exception as e:
                if not is_retryable_llm_error(e):
                    logger.error("Query embedding failed with non-retryable error", error=str(e))
                    return []
                wait = 2 ** attempt
                logger.warning(
                    "Query embedding attempt failed",
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(wait)

        logger.error("Query embedding failed permanently")
        return []
