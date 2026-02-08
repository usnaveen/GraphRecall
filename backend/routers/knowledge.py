"""Knowledge Summary Router - Lightweight global view endpoints."""

import structlog
from fastapi import APIRouter, Depends

from backend.auth.middleware import get_current_user
from backend.db.neo4j_client import get_neo4j_client
from backend.services.community_service import CommunityService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge"])


@router.get("/summary")
async def get_knowledge_summary(current_user: dict = Depends(get_current_user)):
    """Return a lightweight global summary of the user's knowledge."""
    user_id = str(current_user["id"])
    neo4j = await get_neo4j_client()

    domain_stats = await neo4j.execute_query(
        """
        MATCH (c:Concept {user_id: $uid})
        RETURN c.domain AS domain,
               count(c) AS concept_count,
               avg(c.complexity_score) AS avg_complexity,
               collect(c.name)[0..5] AS sample_concepts
        ORDER BY concept_count DESC
        """,
        {"uid": user_id},
    )

    community_service = CommunityService()
    communities = await community_service.get_communities(user_id)

    return {
        "domains": domain_stats,
        "communities": [
            {
                "title": c.get("title"),
                "size": c.get("size"),
                "summary": c.get("summary", ""),
            }
            for c in communities
        ],
        "total_concepts": sum(d.get("concept_count", 0) for d in domain_stats),
    }
