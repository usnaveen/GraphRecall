"""Re-embed child chunks that were saved without a vector.

embed_node saves a note's chunks even when the embedding call fails (a quota error, a timeout),
so the text is never lost. Until those chunks get a vector they are invisible to vector search.
This fills them in with the same call embed_node makes.
"""

from __future__ import annotations

from typing import Optional

import structlog

logger = structlog.get_logger()

_MISSING_SQL = """
SELECT c.id::text AS id, c.content
FROM chunks c JOIN notes n ON c.note_id = n.id
WHERE n.user_id = CAST(:user_id AS uuid)
  AND c.chunk_level = 'child'
  AND c.embedding IS NULL
  {note_filter}
ORDER BY c.id
"""


async def count_missing_embeddings(pg, user_id: str, note_id: Optional[str] = None) -> int:
    rows = await pg.execute_query(
        _MISSING_SQL.format(note_filter="AND c.note_id = CAST(:note_id AS uuid)" if note_id else ""),
        {"user_id": user_id, **({"note_id": note_id} if note_id else {})},
    )
    return len(rows)


async def reembed_missing_chunks(
    user_id: str,
    note_id: Optional[str] = None,
    *,
    pg=None,
    embedder=None,
    batch_size: int = 20,
) -> dict:
    """Embed every child chunk of `user_id` (optionally one note) that has no vector.

    Returns {"missing_before", "embedded", "still_missing"}. Stops at the first batch that
    returns nothing (the provider is still failing), so a dead quota costs one call, not N.
    """
    if pg is None:
        from backend.db.postgres_client import get_postgres_client

        pg = await get_postgres_client()
    if embedder is None:
        from backend.services.ingestion.embedding_service import EmbeddingService

        embedder = EmbeddingService()

    params = {"user_id": user_id, **({"note_id": note_id} if note_id else {})}
    rows = await pg.execute_query(
        _MISSING_SQL.format(note_filter="AND c.note_id = CAST(:note_id AS uuid)" if note_id else ""), params
    )
    embedded = 0
    for start in range(0, len(rows), batch_size):
        part = rows[start:start + batch_size]
        vectors = await embedder.embed_batch([r["content"] for r in part]) or []
        wrote = 0
        for row, vec in zip(part, vectors):
            if vec:
                await pg.execute_update(
                    "UPDATE chunks SET embedding = CAST(:e AS vector) WHERE id = CAST(:id AS uuid)",
                    {"e": "[" + ",".join(str(x) for x in vec) + "]", "id": row["id"]},
                )
                wrote += 1
        embedded += wrote
        if wrote == 0:
            break
    result = {"missing_before": len(rows), "embedded": embedded, "still_missing": len(rows) - embedded}
    logger.info("reembed_missing_chunks", user_id=user_id, note_id=note_id, **result)
    return result
