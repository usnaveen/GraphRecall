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
    """Return a lightweight global summary of the user's knowledge.

    Response shape:
    {
        "domains": [ {domain, concept_count, avg_complexity, sample_concepts} ],
        "communities": [ {title, size, summary} ],
        "total_concepts": int,
        "total_relationships": int,
        "strongest_connections": [ {from, to, type, strength, mentions} ]
    }
    """
    user_id = str(current_user["id"])
    neo4j = await get_neo4j_client()

    domain_stats = await neo4j.execute_query(
        """
        MATCH (c:Concept {user_id: $uid})
        RETURN c.domain AS domain,
               count(c) AS concept_count,
               avg(c.complexity_score) AS avg_complexity,
               avg(c.confidence) AS avg_confidence,
               collect(c.name)[0..5] AS sample_concepts
        ORDER BY concept_count DESC
        """,
        {"uid": user_id},
    )

    # Get relationship stats — total count and strongest connections
    rel_stats = await neo4j.execute_query(
        """
        MATCH (c1:Concept {user_id: $uid})-[r]->(c2:Concept {user_id: $uid})
        RETURN count(r) AS total_relationships
        """,
        {"uid": user_id},
    )
    total_rels = rel_stats[0]["total_relationships"] if rel_stats else 0

    strongest = await neo4j.execute_query(
        """
        MATCH (c1:Concept {user_id: $uid})-[r]->(c2:Concept {user_id: $uid})
        WHERE r.mention_count IS NOT NULL
        RETURN c1.name AS from_concept, c2.name AS to_concept,
               type(r) AS type, r.strength AS strength,
               r.mention_count AS mentions
        ORDER BY r.mention_count DESC, r.strength DESC
        LIMIT 10
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
        "total_relationships": total_rels,
        "strongest_connections": strongest,
    }
