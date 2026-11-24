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


async def filter_by_domains(neo4j_client, user_id: str, items: list[FeedItem],
                            domains: Optional[list[str]]) -> list[FeedItem]:
    """Respect the feed's ``domains`` (topic) filter: keep only agent cards tagged with at
    least one of the user's concepts in those domains. Untagged cards are dropped when a
    filter is active (we can't tell which topic they belong to)."""
    if not domains:
        return items
    cids = sorted({c for it in items for c in (it.content.get("concept_ids") or [])})
    if not cids:
        return []
    rows = await neo4j_client.execute_query(
        """
        MATCH (c:Concept) WHERE c.id IN $ids AND c.user_id = $user_id
        RETURN c
        """,
        {"ids": cids, "user_id": user_id},
    )
    wanted = set(domains)
    in_scope = {r["c"]["id"] for r in rows if r.get("c") and r["c"].get("domain") in wanted}
    out = []
    for it in items:
        tagged = [c for c in it.content.get("concept_ids") or [] if c in in_scope]
        if tagged:
            if it.concept_id not in in_scope:
                it.concept_id = tagged[0]
            out.append(it)
    return out


def merge_into_feed(curated: list[FeedItem], items: list, max_items: int,
                    max_curated: int = 5) -> list:
    """Prepend curated cards without exceeding the caller's ``max_items``. At most
    ``max_curated`` cards and never more than half the page when the page has room for
    ordinary items too."""
    if max_items <= 0:
        return []
    cap = min(max_curated, max_items if max_items < 2 else max(1, max_items // 2))
    return (curated[:cap] + list(items))[:max_items]
