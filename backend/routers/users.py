from fastapi import APIRouter, HTTPException
import structlog

from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client

router = APIRouter(prefix="/api/users", tags=["users"])
logger = structlog.get_logger()

@router.delete("/me/purge", status_code=204)
async def purge_user_data(user_id: str = "default_user"):
    """
    DANGER: Permanently delete ALL data for the current user.
    Removes data from both Postgres and Neo4j.
    """
    logger.warning("Purge initiated", user_id=user_id)
    
    try:
        # 1. Purge Neo4j (Graph)
        neo4j = await get_neo4j_client()
        await neo4j.execute_update(
            "MATCH (n) WHERE n.user_id = $user_id DETACH DELETE n",
            {"user_id": user_id}
        )
        logger.info("Purged Neo4j data", user_id=user_id)

        # 2. Purge Postgres (Relational)
        # Order matters due to Foreign Keys!
        pg = await get_postgres_client()
        queries = [
            "DELETE FROM study_sessions WHERE user_id = :uid",
            "DELETE FROM proficiency_scores WHERE user_id = :uid",
            "DELETE FROM quiz_candidates WHERE user_id = :uid",
            "DELETE FROM generated_content WHERE user_id = :uid",
            "DELETE FROM user_uploads WHERE user_id = :uid",
            "DELETE FROM flashcards WHERE user_id = :uid",
            "DELETE FROM quizzes WHERE user_id = :uid",
            "DELETE FROM chunks WHERE note_id IN (SELECT id FROM notes WHERE user_id = :uid)",
            "DELETE FROM notes WHERE user_id = :uid",
        ]
        
        for q in queries:
            await pg.execute_update(q, {"uid": user_id})
            
        logger.info("Purged Postgres data", user_id=user_id)
        
    except Exception as e:
        logger.error("Purge failed", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
