"""YouTube import: video -> timestamped transcript note -> the normal ingestion pipeline.

Shared by the app's ``POST /api/v2/ingest/youtube`` and the agent bridge's ingest tasks, so both get
the same behaviour: captions first, Gemini watching the video when captions are missing or blocked,
deduplication per user by video id, and link-only storage (status "stored") when no transcript can
be had. See ``backend/services/ingestion/youtube.py`` for the transcript side.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


async def _store_link_only(user_id: str, url: str, title: str) -> str:
    """The old behaviour, kept as the last resort: a note that holds the link and nothing else."""
    from backend.db.postgres_client import get_postgres_client

    note_id = str(uuid.uuid4())
    pg = await get_postgres_client()
    await pg.execute_update(
        """
        INSERT INTO notes (id, user_id, title, content_text, resource_type, source_url, created_at, updated_at)
        VALUES (:id, :user_id, :title, :content_text, 'youtube', :source_url, :created_at, :created_at)
        """,
        {"id": note_id, "user_id": user_id, "title": title, "content_text": f"YouTube link: {url}",
         "source_url": url, "created_at": datetime.now(timezone.utc)},
    )
    return note_id


async def import_video(user_id: str, url: str, title: Optional[str] = None) -> dict:
    """Import one YouTube video for a user. Raises ``YouTubeError`` for links that aren't videos.

    Returns the endpoint's response body: note_id, status ("completed" | "stored"), status_reason
    (e.g. "completed_duplicate", "no_transcript"), title, channel, transcript_source, concepts,
    concept_ids, flashcard_ids, warnings, ...
    """
    from backend.db.postgres_client import get_postgres_client
    from backend.graphs.article_graph import _existing_note, url_hash
    from backend.graphs.ingestion_graph import run_ingestion
    from backend.routers.ingest_v2 import _enqueue_note_ingested_event, _schedule_reembed_if_needed
    from backend.services.ingestion import youtube as yt

    video_id = yt.parse_video_id(url)
    url = yt.watch_url(video_id)
    content_hash = url_hash(url)
    base = {"resource_type": "youtube", "url": url, "video_id": video_id}

    dup = await _existing_note(user_id, content_hash)
    if dup:
        return {**base, "note_id": dup, "status": "completed", "status_reason": "completed_duplicate",
                "transcript_source": None, "concepts": [], "concept_ids": [],
                "warnings": ["already in your library: this video was imported before"]}

    v = await yt.get_transcript(url)
    title = title or v.title or f"YouTube: {url}"
    if not v.ok:
        note_id = await _store_link_only(user_id, url, title)
        logger.info("youtube_import: link only", note_id=note_id, video_id=video_id)
        return {**base, "note_id": note_id, "status": "stored", "status_reason": "no_transcript",
                "title": title, "transcript_source": "none", "concepts": [], "concept_ids": [],
                "warnings": v.warnings}

    ingestion = dict(await run_ingestion(content=yt.render_note(v), title=title, user_id=user_id,
                                         skip_review=True, content_hash=content_hash,
                                         resource_type="youtube") or {})
    note_id = ingestion.get("note_id")
    if note_id:
        pg = await get_postgres_client()
        await pg.execute_update("UPDATE notes SET source_url = :u WHERE id = :id AND user_id = :uid",
                                {"u": url, "id": str(note_id), "uid": user_id})
    await _schedule_reembed_if_needed(ingestion, user_id)
    if note_id and ingestion.get("status", "completed") == "completed":
        await _enqueue_note_ingested_event(user_id, note_id, title, ingestion.get("concepts", []) or [])
    logger.info("youtube_import: ingested", note_id=note_id, video_id=video_id, source=v.source,
                chars=len(v.text), concepts=len(ingestion.get("concepts") or []))
    return {
        **base,
        "note_id": note_id,
        "status": ingestion.get("status", "completed"),
        "status_reason": ingestion.get("status_reason", "completed"),
        "next_action": ingestion.get("next_action", "none"),
        "thread_id": ingestion.get("thread_id", ""),
        "title": title,
        "channel": v.channel,
        "transcript_source": v.source,
        "language": v.language,
        "concepts": ingestion.get("concepts", []),
        "concept_ids": ingestion.get("concept_ids", []),
        "flashcard_ids": ingestion.get("flashcard_ids", []),
        "error": ingestion.get("error"),
        "warnings": list(ingestion.get("warnings") or []) + v.warnings,
    }
