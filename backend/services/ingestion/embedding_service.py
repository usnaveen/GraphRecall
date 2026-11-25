import asyncio
import hashlib
import os
import re
from typing import List, Optional
import structlog
from backend.config.llm import get_embeddings, get_embedding_dims

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
CACHE_ENABLED = os.getenv("EMBEDDING_CACHE", "1") != "0"


def _model_name(embedder) -> str:
    return str(getattr(embedder, "model", None) or getattr(embedder, "model_name", None) or "embedding")


def cache_key(model: str, dims: int, text: str) -> str:
    return hashlib.sha256(f"{model}|{dims}|{text}".encode("utf-8")).hexdigest()

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

    async def _embed_with_retry(self, texts: List[str]) -> List[List[float]]:
        """Embed a small batch with exponential backoff retry."""
        for attempt in range(MAX_RETRIES):
            try:
                embeddings = await self.embedder.aembed_documents(
                    texts,
                    output_dimensionality=self.dims,
                )
                return embeddings
            except Exception as e:
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
        return []

    async def embed_batch(self, texts: List[str], owner: Optional[str] = None) -> List[List[float]]:
        """Embed a batch of texts for storage (retrieval_document task).

        With ``owner`` (a user id), vectors already computed for the same text, model and dims
        come from the per-user embedding cache; only the misses hit the API.
        """
        if not owner or not CACHE_ENABLED or not _UUID.match(str(owner)) or not texts:
            return await self._embed_uncached(texts)
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
        missing = [i for i, k in enumerate(keys) if k not in hits]
        fresh = await self._embed_uncached([texts[i] for i in missing]) if missing else []
        out: List[List[float]] = [hits.get(k, []) for k in keys]
        for i, vec in zip(missing, fresh):
            out[i] = vec
        logger.info("embed_batch: cache", total=len(texts), hits=len(texts) - len(missing))
        if pg is not None and missing:
            try:
                for i, vec in zip(missing, fresh):
                    if vec:
                        await pg.execute_update(
                            "INSERT INTO embedding_cache (key, user_id, model, dims, embedding) "
                            "VALUES (:k, CAST(:u AS uuid), :m, :d, :e) ON CONFLICT DO NOTHING",
                            {"k": keys[i], "u": owner, "m": model, "d": self.dims, "e": [float(x) for x in vec]},
                        )
            except Exception as e:  # noqa: BLE001
                logger.warning("embedding cache write failed", error=str(e)[:200])
        return out

    async def _embed_uncached(self, texts: List[str]) -> List[List[float]]:
        """Embed via the API: splits large batches and retries on failure."""
        if not self.embedder:
            logger.error("Embedding service not configured")
            return []

        if not texts:
            return []

        # Split into smaller batches to avoid API limits
        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), MAX_BATCH_SIZE):
            batch = texts[i:i + MAX_BATCH_SIZE]
            batch_embeddings = await self._embed_with_retry(batch)

            if not batch_embeddings:
                # If full batch fails, try one-by-one as last resort
                logger.warning(
                    "Batch embedding failed, falling back to individual embedding",
                    batch_start=i,
                    batch_size=len(batch),
                )
                for j, text in enumerate(batch):
                    single = await self._embed_with_retry([text])
                    if single:
                        all_embeddings.append(single[0])
                    else:
                        logger.error(
                            "Individual embedding failed permanently",
                            text_index=i + j,
                            text_preview=text[:80],
                        )
                        all_embeddings.append([])  # Placeholder - will be caught downstream
            else:
                all_embeddings.extend(batch_embeddings)

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

        for attempt in range(MAX_RETRIES):
            try:
                return await self.embedder.aembed_query(
                    text,
                    output_dimensionality=self.dims,
                )
            except Exception as e:
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
