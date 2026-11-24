"""Turn approved agent-curated items into regular ``FeedItem`` objects.

Only ``approved`` items whose ``target_date`` is today (or the last few days, if the
user has not opened the app) are shown. Every item carries provenance so the UI can
label it "Curated by your agent" and link the source.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from backend.agent_bridge.repository import BridgeRepository
from backend.models.feed_schemas import FeedItem, FeedItemType

LOOKBACK_DAYS = 2


def to_feed_item(row: dict) -> FeedItem:
    body = row.get("body_json") or {}
    concept_ids = row.get("concept_ids") or []
    td = row.get("target_date")
    due = datetime.combine(td, time.min, tzinfo=timezone.utc) if isinstance(td, date) else None
    return FeedItem(
        id=f"agent:{row['id']}",
        item_type=FeedItemType.AGENT_CURATED,
        concept_id=concept_ids[0] if concept_ids else None,
        due_date=due,
        priority_score=1.5,  # above ordinary due items; TODO(agent-bridge): tune ranking
        content={
            "title": row["title"],
            "summary": row["summary"],
            "reason": row["reason"],
            "source_url": row.get("source_url"),
            "source_kind": row.get("source_kind"),
            "item_kind": row.get("item_kind"),
            "flashcard": body.get("flashcard"),
            "concept_ids": concept_ids,
            "provenance": {
                "curated_by": "agent",
                "agent_key_id": row.get("key_id"),
                "agent_feed_item_id": row["id"],
                "label": "Curated by your agent",
            },
        },
    )


async def agent_feed_items(repo: BridgeRepository, user_id: str,
                           today: Optional[date] = None, limit: int = 10) -> list[FeedItem]:
    today = today or datetime.now(timezone.utc).date()
    rows: list[dict] = []
    for offset in range(LOOKBACK_DAYS + 1):
        rows += await repo.list_feed_items(user_id, status="approved",
                                           target_date=today - timedelta(days=offset),
                                           limit=limit)
        if len(rows) >= limit:
            break
    # TODO(agent-bridge): hide items the user already opened/dismissed (needs an
    # interaction column or reuse of the like/save tables).
    return [to_feed_item(r) for r in rows[:limit]]
