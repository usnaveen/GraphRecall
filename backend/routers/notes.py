"""Notes Router - List and delete user notes."""

import structlog

from backend.services.storage_service import get_storage_service
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth.middleware import get_current_user
from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client

logger = structlog.get_logger()

router = APIRouter(prefix="/api/notes", tags=["Notes"])


@router.get("")
async def list_notes(
    current_user: dict = Depends(get_current_user),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    resource_type: str = Query(default=None, description="Filter by resource_type (e.g. 'book', 'notes', 'article')"),
):
    """List notes for the current user, optionally filtered by resource_type."""
    try:
        pg_client = await get_postgres_client()
        user_id = str(current_user["id"])

        params: dict = {"user_id": user_id, "limit": limit, "offset": offset}

        where_clause = "WHERE user_id = :user_id"
        if resource_type:
            where_clause += " AND resource_type = :resource_type"
            params["resource_type"] = resource_type

        notes = await pg_client.execute_query(
            f"""
            SELECT id, title, content_text, resource_type, source_url, created_at
            FROM notes
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        count_result = await pg_client.execute_query(
            f"SELECT COUNT(*) as count FROM notes {where_clause}",
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result[0]["count"] if count_result else 0

        # Ensure UUIDs are serialized as strings
        for n in notes:
            if n.get("id"):
                n["id"] = str(n["id"])

        return {
            "notes": notes,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error("Notes: Error listing notes", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


CONCEPT_ROW_TABLES = ("flashcards", "quizzes", "proficiency_scores", "generated_content", "study_sessions")


async def delete_concept_rows(pg, user_id: str, concept_ids: list[str]) -> int:
    """Delete the user's study rows for concepts that no longer exist (cards and quizzes generated
    from the deleted note's text, scores and review history). Only tables that have both columns."""
    if not concept_ids:
        return 0
    rows = await pg.execute_query(
        "SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' "
        "AND column_name IN ('user_id', 'concept_id') AND table_name = ANY(:t) "
        "GROUP BY table_name HAVING count(*) = 2", {"t": list(CONCEPT_ROW_TABLES)})
    deleted = 0
    for t in sorted(r["table_name"] for r in rows):
        res = await pg.execute_query(
            f"DELETE FROM {t} WHERE user_id = CAST(:u AS uuid) AND concept_id = ANY(:ids) RETURNING 1 AS x",
            {"u": user_id, "ids": concept_ids})
        deleted += len(res)
    return deleted


async def delete_note_graph(neo4j, note_id: str, user_id: str) -> list[str]:
    """Delete the note's NoteSource and every Concept that no other note of this user explains.
    Returns the ids of the deleted concepts."""
    rows = await neo4j.execute_query(
        """
        MATCH (n:NoteSource {id: $note_id, user_id: $user_id})
        OPTIONAL MATCH (n)-[:EXPLAINS]->(c:Concept {user_id: $user_id})
        WHERE NOT EXISTS {
            MATCH (other:NoteSource {user_id: $user_id})-[:EXPLAINS]->(c) WHERE other.id <> $note_id
        }
        WITH n, collect(DISTINCT c) AS orphans
        WITH n, orphans, [c IN orphans | c.id] AS ids
        FOREACH (c IN orphans | DETACH DELETE c)
        DETACH DELETE n
        RETURN ids
        """,
        {"note_id": note_id, "user_id": user_id},
    )
    return [i for i in (rows[0]["ids"] if rows else []) if i]


@router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a note for the current user."""
    try:
        pg_client = await get_postgres_client()
        user_id = str(current_user["id"])

        result = await pg_client.execute_query(
            "SELECT id FROM notes WHERE id = :note_id AND user_id = :user_id",
            {"note_id": note_id, "user_id": user_id},
        )

        if not result:
            raise HTTPException(status_code=404, detail="Note not found")

        # Images stored for this note's chunks (collected before the cascade removes the chunks).
        image_urls: list[str] = []
        try:
            from backend.services.account_deletion import _image_urls

            for r in await pg_client.execute_query(
                    "SELECT c.images FROM chunks c JOIN notes n ON n.id = c.note_id "
                    "WHERE n.id = :note_id AND n.user_id = :user_id AND c.images IS NOT NULL",
                    {"note_id": note_id, "user_id": user_id}):
                image_urls += _image_urls(r.get("images"))
        except Exception as e:
            logger.warning("Notes: could not collect note images", error=str(e))

        await pg_client.execute_update(
            "DELETE FROM notes WHERE id = :note_id AND user_id = :user_id",
            {"note_id": note_id, "user_id": user_id},
        )

        # Best-effort graph cleanup: concepts extracted only from this note go with it (their
        # definitions are derived from its text), then the NoteSource node itself.
        try:
            neo4j = await get_neo4j_client()
            removed = await delete_note_graph(neo4j, note_id, user_id)
            await delete_concept_rows(pg_client, user_id, removed)
        except Exception as e:
            logger.warning("Notes: Failed to delete note graph", error=str(e))

        if image_urls:
            try:
                storage = get_storage_service()
                for url in dict.fromkeys(image_urls):
                    await storage.delete_file(url, owner_id=user_id)
            except Exception as e:
                logger.warning("Notes: note images not deleted", error=str(e))

        return {"status": "deleted", "note_id": note_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Notes: Error deleting note", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
