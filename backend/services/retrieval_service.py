"""
Hybrid Retrieval Service: Vector + Keyword + Graph

Combines three retrieval strategies with Reciprocal Rank Fusion (RRF)
to produce the best context for RAG responses.

1. Vector Search — pgvector cosine similarity on child chunks
2. Keyword Search — ILIKE fallback for exact term matches
3. Graph Search — Neo4j k-hop traversal for relationship context
"""

import asyncio
import json
from typing import List, Dict, Any, Optional

import structlog
from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client
from backend.services.ingestion.embedding_service import EmbeddingService

logger = structlog.get_logger()

# RRF constant (standard value from literature)
RRF_K = 60


class RetrievalService:
    """
    Hybrid Retrieval Service (Vector + Keyword + Graph).

    Uses Reciprocal Rank Fusion to merge results from multiple strategies
    into a single ranked list.
    """

    def __init__(self):
        self.embedding_service = EmbeddingService()

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
        include_graph: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Perform hybrid search combining vector, keyword, and graph retrieval.

        Args:
            query: Natural language query
            user_id: User ID for scoping
            limit: Max results to return
            include_graph: Whether to include graph context

        Returns:
            List of results sorted by fused relevance score
        """
        logger.info("hybrid_search: Starting", query=query[:80], user_id=user_id)

        # Run all retrieval strategies in parallel
        tasks = [
            self._vector_search(query, user_id, limit=limit * 2),
            self._keyword_search(query, user_id, limit=limit),
        ]
        if include_graph:
            tasks.append(self._graph_search(query, user_id, limit=limit))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        vector_results = results[0] if not isinstance(results[0], Exception) else []
        keyword_results = results[1] if not isinstance(results[1], Exception) else []
        graph_results = results[2] if len(results) > 2 and not isinstance(results[2], Exception) else []

        # Merge with Reciprocal Rank Fusion
        fused = self._reciprocal_rank_fusion(
            vector_results, keyword_results, graph_results
        )

        logger.info(
            "hybrid_search: Complete",
            vector=len(vector_results),
            keyword=len(keyword_results),
            graph=len(graph_results),
            fused=len(fused),
        )

        return fused[:limit]

    # =========================================================================
    # Strategy 1: Vector Search (pgvector cosine similarity)
    # =========================================================================

    async def _vector_search(
        self, query: str, user_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Semantic vector search on child chunks with parent context."""
        query_embedding = await self.embedding_service.embed_query(query)
        if not query_embedding:
            return []

        pg_client = await get_postgres_client()
        embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"

        rows = await pg_client.execute_query(
            """
            SELECT
                c.id,
                c.content as child_content,
                c.chunk_index,
                p.content as parent_content,
                c.source_location,
                c.page_start,
                c.page_end,
                c.note_id,
                c.images,
                n.title as note_title,
                1 - (c.embedding <=> cast(:embedding as vector)) as similarity
            FROM chunks c
            LEFT JOIN chunks p ON c.parent_chunk_id = p.id
            JOIN notes n ON c.note_id = n.id
            WHERE c.chunk_level = 'child'
              AND c.embedding IS NOT NULL
              AND n.user_id = :user_id
            ORDER BY c.embedding <=> cast(:embedding as vector)
            LIMIT :limit
            """,
            {"embedding": embedding_literal, "user_id": user_id, "limit": limit},
        )

        results = []
        for row in rows or []:
            r = dict(row)
            r["_source"] = "vector"
            r["_score"] = float(r.get("similarity", 0))
            # Prefer parent content for richer context
            r["content"] = r.get("parent_content") or r.get("child_content", "")
            # Parse images
            images = r.get("images")
            if isinstance(images, str):
                try:
                    r["images"] = json.loads(images)
                except Exception:
                    r["images"] = []
            results.append(r)

        return results

    # =========================================================================
    # Strategy 2: Keyword Search (ILIKE fallback)
    # =========================================================================

    async def _keyword_search(
        self, query: str, user_id: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Keyword-based fallback for exact term matches."""
        pg_client = await get_postgres_client()

        # Extract first 3 significant words for keyword matching
        words = [w for w in query.split() if len(w) > 3][:3]
        if not words:
            return []

        # Build OR pattern for multiple keywords
        patterns = [f"%{w}%" for w in words]

        rows = await pg_client.execute_query(
            """
            SELECT
                c.id,
                c.content as child_content,
                p.content as parent_content,
                c.page_start,
                c.page_end,
                c.note_id,
                c.images,
                n.title as note_title
            FROM chunks c
            LEFT JOIN chunks p ON c.parent_chunk_id = p.id
            JOIN notes n ON c.note_id = n.id
            WHERE n.user_id = :user_id
              AND c.chunk_level = 'child'
              AND (c.content ILIKE :p1 OR c.content ILIKE :p2 OR c.content ILIKE :p3)
            ORDER BY n.updated_at DESC
            LIMIT :limit
            """,
            {
                "user_id": user_id,
                "p1": patterns[0] if len(patterns) > 0 else "%%",
                "p2": patterns[1] if len(patterns) > 1 else "%%",
                "p3": patterns[2] if len(patterns) > 2 else "%%",
                "limit": limit,
            },
        )

        results = []
        for row in rows or []:
            r = dict(row)
            r["_source"] = "keyword"
            r["_score"] = 0.5  # Fixed score for keyword matches
            r["content"] = r.get("parent_content") or r.get("child_content", "")
            images = r.get("images")
            if isinstance(images, str):
                try:
                    r["images"] = json.loads(images)
                except Exception:
                    r["images"] = []
            results.append(r)

        return results

    # =========================================================================
    # Strategy 3: Graph Search (Neo4j k-hop traversal)
    # =========================================================================

    async def _graph_search(
        self, query: str, user_id: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Graph-based retrieval: find concepts matching query, then traverse."""
        try:
            neo4j = await get_neo4j_client()

            # Find seed concepts matching the query
            seeds = await neo4j.execute_query(
                """
                MATCH (c:Concept)
                WHERE c.user_id = $user_id
                  AND (toLower(c.name) CONTAINS toLower($query)
                       OR toLower(c.definition) CONTAINS toLower($query))
                RETURN c.id as id, c.name as name, c.definition as definition,
                       c.domain as domain
                ORDER BY size(c.name) ASC
                LIMIT 5
                """,
                {"user_id": user_id, "query": query},
            )

            if not seeds:
                return []

            # Expand 1-hop from seed concepts
            seed_ids = [s["id"] for s in seeds if s.get("id")]
            neighbors = await neo4j.execute_query(
                """
                MATCH (c:Concept)-[r]-(related:Concept)
                WHERE c.id IN $ids AND related.user_id = $user_id
                RETURN DISTINCT related.id as id, related.name as name,
                       related.definition as definition, related.domain as domain,
                       type(r) as rel_type, c.name as via_concept
                LIMIT $limit
                """,
                {"ids": seed_ids, "user_id": user_id, "limit": limit * 2},
            )

            # Combine seeds + neighbors as graph results
            results = []
            seen_ids = set()
            for concept in seeds + (neighbors or []):
                cid = concept.get("id")
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                results.append({
                    "id": cid,
                    "content": f"{concept.get('name', '')}: {concept.get('definition', '')}",
                    "note_title": f"[Graph] {concept.get('domain', 'General')}",
                    "_source": "graph",
                    "_score": 0.7 if concept in seeds else 0.4,
                    "concept_name": concept.get("name"),
                    "concept_domain": concept.get("domain"),
                })

            return results[:limit]

        except Exception as e:
            logger.warning("graph_search: Failed", error=str(e))
            return []

    # =========================================================================
    # Reciprocal Rank Fusion (RRF)
    # =========================================================================

    def _reciprocal_rank_fusion(
        self,
        *result_lists: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Merge multiple ranked lists using Reciprocal Rank Fusion.

        RRF score = sum(1 / (k + rank_i)) across all lists where item appears.
        This is the standard industry approach for hybrid search fusion.
        """
        scores: Dict[str, float] = {}
        items: Dict[str, Dict] = {}

        for result_list in result_lists:
            for rank, item in enumerate(result_list):
                # Use chunk ID as key, fall back to content hash
                key = str(item.get("id", hash(item.get("content", ""))))
                rrf_score = 1.0 / (RRF_K + rank + 1)
                scores[key] = scores.get(key, 0.0) + rrf_score

                # Keep the best version of each item (highest original score)
                if key not in items or item.get("_score", 0) > items[key].get("_score", 0):
                    items[key] = item

        # Sort by fused RRF score
        ranked_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)

        results = []
        for key in ranked_keys:
            item = items[key]
            item["_rrf_score"] = scores[key]
            results.append(item)

        return results
