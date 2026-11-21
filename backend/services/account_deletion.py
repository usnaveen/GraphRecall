"""Delete a user's data, or the whole account (App Store guideline 5.1.1(v): in-app account deletion).

Order: collect file URLs first (uploads and images referenced by the user's chunks), then remove the
user's graph in Neo4j, then the files, then Postgres. Every user-owned table cascades from `users`
(FK ON DELETE CASCADE), so deleting the account is one statement; the explicit per-table deletes
remain for `purge` (wipe data, keep the account) and for older databases without those cascades.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger()

PURGE_TABLES = (  # child tables before parents
    "community_nodes", "communities", "saved_responses", "concept_review_sessions", "study_sessions",
    "proficiency_scores", "quiz_candidates", "generated_content", "flashcards", "quizzes", "daily_stats",
    "user_uploads", "chat_conversations", "notes",
)


async def _tables(pg) -> set[str]:
    rows = await pg.execute_query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    return {r["table_name"] for r in rows}


def _image_urls(images: Any) -> list[str]:
    if isinstance(images, str):
        try:
            images = json.loads(images)
        except ValueError:
            return []
    out = []
    for im in images or []:
        url = im.get("url") if isinstance(im, dict) else im if isinstance(im, str) else None
        if url and url.startswith(("http://", "https://")):
            out.append(url)
    return out


async def delete_user_data(user_id: str, *, delete_account: bool, pg=None, neo4j=None, storage=None) -> dict:
    """Remove everything the user owns. With delete_account, also the user row (they must sign up again)."""
    if pg is None:
        from backend.db.postgres_client import get_postgres_client

        pg = await get_postgres_client()
    if neo4j is None:
        from backend.db.neo4j_client import get_neo4j_client

        neo4j = await get_neo4j_client()
    tables = await _tables(pg)
    counts: dict[str, int] = {}

    # 1. file URLs, before the rows that reference them are gone
    urls: list[str] = []
    if "user_uploads" in tables:
        urls += [r["file_url"] for r in await pg.execute_query(
            "SELECT file_url FROM user_uploads WHERE user_id = CAST(:u AS uuid)", {"u": user_id}) if r.get("file_url")]
    if "chunks" in tables:
        for r in await pg.execute_query(
                "SELECT c.images FROM chunks c JOIN notes n ON n.id = c.note_id "
                "WHERE n.user_id = CAST(:u AS uuid) AND c.images IS NOT NULL", {"u": user_id}):
            urls += _image_urls(r.get("images"))

    # 2. the user's graph (every node carries user_id)
    res = await neo4j.execute_query("MATCH (n {user_id: $u}) WITH n, count(*) AS _ DETACH DELETE n RETURN count(*) AS n",
                                    {"u": user_id})
    counts["neo4j_nodes"] = int(res[0]["n"]) if res else 0

    # 3. stored files (best effort: a missing object must not block deletion)
    deleted_files = 0
    if urls:
        if storage is None:
            from backend.services.storage_service import get_storage_service

            storage = get_storage_service()
        for url in dict.fromkeys(urls):
            try:
                if await storage.delete_file(url):
                    deleted_files += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("account deletion: file not deleted", error=str(e))
    counts["files"] = deleted_files

    # 4. relational data
    if delete_account:
        await pg.execute_update("DELETE FROM users WHERE id = CAST(:u AS uuid)", {"u": user_id})
        counts["account"] = 1
    else:
        if "chat_messages" in tables and "chat_conversations" in tables:
            await pg.execute_update(
                "DELETE FROM chat_messages WHERE conversation_id IN "
                "(SELECT id FROM chat_conversations WHERE user_id = CAST(:u AS uuid))", {"u": user_id})
        for t in PURGE_TABLES:
            if t in tables:
                await pg.execute_update(f"DELETE FROM {t} WHERE user_id = CAST(:u AS uuid)", {"u": user_id})
    logger.warning("user data deleted", delete_account=delete_account, **counts)
    return counts
