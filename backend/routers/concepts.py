"""Concepts Router - Delete concepts and related data."""

import structlog
from fastapi import APIRouter, Depends, HTTPException

from backend.auth.middleware import get_current_user
from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client

logger = structlog.get_logger()

router = APIRouter(prefix="/api/concepts", tags=["Concepts"])


@router.delete("/{concept_id}")
async def delete_concept(
    concept_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a concept and its related data for the current user."""
    try:
        user_id = str(current_user["id"])
        neo4j = await get_neo4j_client()

        # Verify concept exists
        result = await neo4j.execute_query(
            "MATCH (c:Concept {id: $id, user_id: $user_id}) RETURN c.id AS id",
            {"id": concept_id, "user_id": user_id},
        )
        if not result:
            raise HTTPException(status_code=404, detail="Concept not found")

        # Delete concept node + relationships
        await neo4j.execute_query(
            "MATCH (c:Concept {id: $id, user_id: $user_id}) DETACH DELETE c",
            {"id": concept_id, "user_id": user_id},
        )

        # Clean up related relational data
        pg_client = await get_postgres_client()
        await pg_client.execute_update(
            "DELETE FROM proficiency_scores WHERE user_id = :user_id AND concept_id = :concept_id",
            {"user_id": user_id, "concept_id": concept_id},
        )
        await pg_client.execute_update(
            "DELETE FROM flashcards WHERE user_id = :user_id AND concept_id = :concept_id",
            {"user_id": user_id, "concept_id": concept_id},
        )
        await pg_client.execute_update(
            "DELETE FROM quizzes WHERE user_id = :user_id AND concept_id = :concept_id",
            {"user_id": user_id, "concept_id": concept_id},
        )
        await pg_client.execute_update(
            "DELETE FROM generated_content WHERE user_id = :user_id AND concept_id = :concept_id",
            {"user_id": user_id, "concept_id": concept_id},
        )
        await pg_client.execute_update(
            "DELETE FROM study_sessions WHERE user_id = :user_id AND concept_id = :concept_id",
            {"user_id": user_id, "concept_id": concept_id},
        )
        await pg_client.execute_update(
            """
            UPDATE user_uploads
            SET linked_concepts = array_remove(linked_concepts, :concept_id)
            WHERE user_id = :user_id
            """,
            {"user_id": user_id, "concept_id": concept_id},
        )

        return {"status": "deleted", "concept_id": concept_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Concepts: Error deleting concept", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
