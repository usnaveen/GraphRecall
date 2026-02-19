from fastapi import APIRouter, Depends, HTTPException, status
import structlog

from backend.auth.middleware import get_current_user
from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client
from backend.services.storage_service import get_storage_service

router = APIRouter(prefix="/api/users", tags=["users"])
logger = structlog.get_logger()


async def _get_existing_tables(pg_client) -> set[str]:
    rows = await pg_client.execute_query(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        """
    )
    return {row["table_name"] for row in rows if row.get("table_name")}


@router.delete("/me/purge", status_code=status.HTTP_204_NO_CONTENT)
async def purge_user_data(current_user: dict = Depends(get_current_user)):
    """
    DANGER: Permanently delete ALL data for the current user.
    Removes data from both Postgres and Neo4j.
    """
    user_id = str(current_user["id"])
    logger.warning("Purge initiated", user_id=user_id)
    try:
        pg = await get_postgres_client()
        existing_tables = await _get_existing_tables(pg)

        note_ids: list[str] = []
        if "notes" in existing_tables:
            note_rows = await pg.execute_query(
                "SELECT id FROM notes WHERE user_id = :uid",
                {"uid": user_id},
            )
            note_ids = [str(row["id"]) for row in note_rows if row.get("id")]

        # 1. Purge Neo4j (graph + legacy note nodes by note_id fallback)
        neo4j = await get_neo4j_client()
        await neo4j.execute_query(
            "MATCH (n) WHERE n.user_id = $user_id DETACH DELETE n",
            {"user_id": user_id},
        )
        if note_ids:
            await neo4j.execute_query(
                "MATCH (n:NoteSource) WHERE n.note_id IN $note_ids DETACH DELETE n",
                {"note_ids": note_ids},
            )
        logger.info("Purged Neo4j data", user_id=user_id)

        # 2. Purge Cloud Storage Files (before DB deletes)
        if "user_uploads" in existing_tables:
            uploads = await pg.execute_query(
                "SELECT file_url FROM user_uploads WHERE user_id = :uid",
                {"uid": user_id},
            )

            storage = get_storage_service()
            deleted_files = 0
            for upload in uploads:
                file_url = upload.get("file_url")
                if file_url:
                    try:
                        await storage.delete_file(file_url)
                        deleted_files += 1
                    except Exception as e:
                        logger.warning("Purge: Failed to delete file", file_url=file_url, error=str(e))
            logger.info("Purged storage files", count=deleted_files, user_id=user_id)

        # 3. Purge Postgres (Relational)
        # Order matters due to foreign keys.
        queries: list[tuple[str, str]] = [
            ("community_nodes", "DELETE FROM community_nodes WHERE user_id = :uid"),
            ("communities", "DELETE FROM communities WHERE user_id = :uid"),
            ("saved_responses", "DELETE FROM saved_responses WHERE user_id = :uid"),
            ("concept_review_sessions", "DELETE FROM concept_review_sessions WHERE user_id = :uid"),
            ("study_sessions", "DELETE FROM study_sessions WHERE user_id = :uid"),
            ("proficiency_scores", "DELETE FROM proficiency_scores WHERE user_id = :uid"),
            ("quiz_candidates", "DELETE FROM quiz_candidates WHERE user_id = :uid"),
            ("generated_content", "DELETE FROM generated_content WHERE user_id = :uid"),
            ("flashcards", "DELETE FROM flashcards WHERE user_id = :uid"),
            ("quizzes", "DELETE FROM quizzes WHERE user_id = :uid"),
            ("daily_stats", "DELETE FROM daily_stats WHERE user_id = :uid"),
            ("user_uploads", "DELETE FROM user_uploads WHERE user_id = :uid"),
            ("chat_conversations", "DELETE FROM chat_conversations WHERE user_id = :uid"),
            ("notes", "DELETE FROM notes WHERE user_id = :uid"),
        ]

        # Legacy safety: remove chat_messages if chat_conversations table exists.
        if "chat_messages" in existing_tables and "chat_conversations" in existing_tables:
            await pg.execute_update(
                """
                DELETE FROM chat_messages
                WHERE conversation_id IN (
                    SELECT id FROM chat_conversations WHERE user_id = :uid
                )
                """,
                {"uid": user_id},
            )

        for table_name, query in queries:
            if table_name in existing_tables:
                await pg.execute_update(query, {"uid": user_id})

        logger.info("Purged Postgres data", user_id=user_id)

    except Exception as e:
        logger.error("Purge failed", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
