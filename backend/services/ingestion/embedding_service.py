import asyncio
from typing import List
import structlog
from backend.config.llm import get_embeddings, get_embedding_dims

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

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts for storage (retrieval_document task).

        Splits large batches and retries on failure.
        """
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
