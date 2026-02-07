from typing import List, Dict, Any
import os
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.embeddings import Embeddings
import structlog

logger = structlog.get_logger()

class EmbeddingService:
    """
    Service for generating vector embeddings for document chunks.
    Configured to use Gemini Embeddings (text-embedding-004) by default.
    """
    
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("GOOGLE_API_KEY not set. Embedding service will fail.")
            self.embedder = None
        else:
            self.embedder = GoogleGenerativeAIEmbeddings(
                model="models/embedding-001",
                google_api_key=self.api_key,
                task_type="retrieval_document"
            )

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a batch of texts.
        """
        if not self.embedder:
            logger.error("Embedding service not configured")
            return []
            
        try:
            # LangChain's Google integration is synchronous or async depending on version, 
            # typically safe to run in threadpool or direct async if supported.
            # aembed_documents is the async method.
            embeddings = await self.embedder.aembed_documents(texts)
            return embeddings
        except Exception as e:
            logger.error("Embedding generation failed", error=str(e))
            return []

    async def embed_query(self, text: str) -> List[float]:
        """
        Embed a search query.
        """
        if not self.embedder:
            return []
            
        try:
            # For query, we might need task_type="retrieval_query" if strictly following Gemini API,
            # but LangChain wrapper usually handles this or uses default.
            # Re-init for query might be needed if strictly typed, but usually fine.
            return await self.embedder.aembed_query(text)
        except Exception as e:
            logger.error("Query embedding failed", error=str(e))
            return []
