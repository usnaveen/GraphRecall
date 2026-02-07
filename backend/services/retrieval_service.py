from typing import List, Dict, Any, Optional
from uuid import UUID
import structlog
from backend.db.postgres_client import get_postgres_client
from backend.services.ingestion.embedding_service import EmbeddingService

logger = structlog.get_logger()

class RetrievalService:
    """
    Service for Hybrid Retrieval (Vector + Keyword + Graph).
    """
    
    def __init__(self):
        self.embedding_service = EmbeddingService()
        
    async def search(self, query: str, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Perform hybrid search.
        Currently implements Vector Search on Child Chunks with Parent Context.
        """
        logger.info("search: Starting", query=query, user_id=user_id)
        
        # 1. Generate Query Embedding
        query_embedding = await self.embedding_service.embed_query(query)
        if not query_embedding:
            logger.warning("search: Failed to embed query")
            return []
            
        # 2. Vector Search (PGVector)
        # We retrieve Child Chunks but also join with Parent Chunk to get full context
        pg_client = await get_postgres_client()
        
        # Use named parameters for SQLAlchemy text()
        # Ensure embedding is passed as string for compatible casting if needed, 
        # though asyncpg can often handle lists. String is safest for vector literal.
        embedding_str = str(query_embedding)
        
        results = await pg_client.execute_query(
            """
            SELECT 
                c.id, 
                c.content as child_content, 
                c.chunk_index,
                p.content as parent_content,
                c.source_location,
                1 - (c.embedding <=> :embedding) as similarity
            FROM chunks c
            LEFT JOIN chunks p ON c.parent_chunk_id = p.id
            WHERE c.chunk_level = 'child'
            ORDER BY c.embedding <=> :embedding
            LIMIT :limit
            """,
            {
                "embedding": embedding_str, 
                "limit": limit
            }
        )
        
        return results

