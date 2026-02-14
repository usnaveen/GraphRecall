"""Notes Router - List and delete user notes."""

import structlog
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

        await pg_client.execute_update(
            "DELETE FROM notes WHERE id = :note_id AND user_id = :user_id",
            {"note_id": note_id, "user_id": user_id},
        )

        # Best-effort: remove note source node from Neo4j
        try:
            neo4j = await get_neo4j_client()
            await neo4j.execute_query(
                """
                MATCH (n:NoteSource {id: $note_id, user_id: $user_id})
                DETACH DELETE n
                """,
                {"note_id": note_id, "user_id": user_id},
            )
        except Exception as e:
            logger.warning("Notes: Failed to delete NoteSource", error=str(e))

        return {"status": "deleted", "note_id": note_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Notes: Error deleting note", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
