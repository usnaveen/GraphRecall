"""Invalidate a user's cached chat answers after edits that only touch the knowledge graph.

Cached answers are keyed on a fingerprint of the user's notes (see chat_graph._cache_partition), so
adding or deleting a note moves them out of reach automatically. Graph-only edits (creating,
linking, deleting, merging or dumping concepts) do not touch the notes table, so they bump the
user's corpus version counter instead. Best effort: a failed bump must never fail the edit.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


async def invalidate_cached_answers(user_id: str) -> None:
    try:
        from backend.graphs.chat_graph import bump_user_corpus_version

        await bump_user_corpus_version(str(user_id))
    except Exception as e:  # pragma: no cover - cache backend down
        logger.warning("answer_cache: invalidation failed", user_id=str(user_id), error=str(e))
