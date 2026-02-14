from typing import List
import structlog
from backend.config.llm import get_embeddings, get_embedding_dims

logger = structlog.get_logger()


class EmbeddingService:
    """
    Service for generating vector embeddings for document chunks.

    Uses gemini-embedding-001 via centralized config (config/llm.py).
    Produces 768-dimensional vectors (MRL-trained, 99.74% quality of 3072).
    """

    def __init__(self):
        self.embedder = get_embeddings()
        self.dims = get_embedding_dims()

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts for storage (retrieval_document task)."""
        if not self.embedder:
            logger.error("Embedding service not configured")
            return []

        try:
            embeddings = await self.embedder.aembed_documents(
                texts,
                output_dimensionality=self.dims,
            )
            return embeddings
        except Exception as e:
            logger.error("Embedding generation failed", error=str(e))
            return []

    async def embed_query(self, text: str) -> List[float]:
        """Embed a search query for retrieval."""
        if not self.embedder:
            return []

        try:
            return await self.embedder.aembed_query(
                text,
                output_dimensionality=self.dims,
            )
        except Exception as e:
            logger.error("Query embedding failed", error=str(e))
            return []
