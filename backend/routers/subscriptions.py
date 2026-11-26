"""REST API for native Substack / RSS reading subscriptions integrated with the Reels Feed."""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from backend.auth.middleware import get_current_user
from backend.db.neo4j_client import Neo4jClient, get_neo4j_client
from backend.db.postgres_client import PostgresClient, get_postgres_client
from backend.services.substack_sync import (
    SubstackSyncError,
    fetch_feed_xml,
    load_user_concepts_with_mastery,
    match_entry_to_concepts,
    normalize_substack_feed_url,
    parse_rss_or_atom,
)

router = APIRouter(prefix="/api/subscriptions/substack", tags=["Substack Subscriptions"])


class AddSubstackRequest(BaseModel):
    publication: str = Field(
        ...,
        min_length=2,
        max_length=2048,
        description="Substack handle (e.g. 'latentnotes'), publication URL, or RSS feed URL",
    )


async def _sync_one_subscription(
    pg: PostgresClient,
    sub_row: dict[str, Any],
    user_concepts: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    xml_bytes = await fetch_feed_xml(sub_row["feed_url"])
    parsed = parse_rss_or_atom(xml_bytes, fallback_site_url=sub_row["site_url"])
    user_id = str(sub_row["user_id"])
    sub_id = str(sub_row["id"])

    updated_rows = await pg.execute_insert(
        """
        UPDATE substack_subscriptions
        SET title = :title,
            author = COALESCE(:author, author),
            site_url = :site_url,
            last_synced_at = CURRENT_TIMESTAMP
        WHERE id = CAST(:sub_id AS uuid)
          AND user_id = CAST(:user_id AS uuid)
        RETURNING id::text AS id, user_id::text AS user_id, feed_url, site_url, title, author, active, last_synced_at
        """,
        {
            "title": parsed.title,
            "author": parsed.author,
            "site_url": parsed.site_url,
            "sub_id": sub_id,
            "user_id": user_id,
        },
    )
    updated_sub = dict(updated_rows[0]) if updated_rows else dict(sub_row)

    upserted = 0
    for entry in parsed.entries:
        matches, score = match_entry_to_concepts(
            entry.title, entry.summary, entry.excerpt_markdown, user_concepts
        )
        await pg.execute_update(
            """
            INSERT INTO substack_feed_articles
                (subscription_id, user_id, article_url, dedupe_key, publication_name, author,
                 title, summary, excerpt_markdown, published_at, matched_concepts, relevance_score)
            VALUES
                (CAST(:sub_id AS uuid), CAST(:user_id AS uuid), :article_url, :dedupe_key,
                 :pub_name, :author, :title, :summary, :excerpt_markdown, :published_at,
                 CAST(:matched_concepts AS jsonb), :relevance_score)
            ON CONFLICT (user_id, dedupe_key) DO UPDATE
            SET matched_concepts = EXCLUDED.matched_concepts,
                relevance_score = EXCLUDED.relevance_score,
                publication_name = EXCLUDED.publication_name
            """,
            {
                "sub_id": sub_id,
                "user_id": user_id,
                "article_url": entry.url,
                "dedupe_key": entry.dedupe_key,
                "pub_name": updated_sub["title"],
                "author": entry.author or updated_sub.get("author"),
                "title": entry.title,
                "summary": entry.summary,
                "excerpt_markdown": entry.excerpt_markdown,
                "published_at": entry.published_at,
                "matched_concepts": json.dumps(matches),
                "relevance_score": score,
            },
        )
        upserted += 1
    return updated_sub, upserted


@router.post("", status_code=201)
async def subscribe_substack(
    body: AddSubstackRequest,
    user: dict = Depends(get_current_user),
    pg: PostgresClient = Depends(get_postgres_client),
    neo4j: Neo4jClient = Depends(get_neo4j_client),
):
    user_id = str(user["id"])
    try:
        feed_url, site_url = normalize_substack_feed_url(body.publication)
        xml_bytes = await fetch_feed_xml(feed_url)
        parsed = parse_rss_or_atom(xml_bytes, fallback_site_url=site_url)
    except SubstackSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # execute_query, not execute_insert: we need the whole RETURNING row (execute_insert gives the id).
    rows = await pg.execute_query(
        """
        INSERT INTO substack_subscriptions (user_id, feed_url, site_url, title, author, active, last_synced_at)
        VALUES (CAST(:user_id AS uuid), :feed_url, :site_url, :title, :author, TRUE, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id, feed_url) DO UPDATE
        SET active = TRUE,
            title = EXCLUDED.title,
            author = COALESCE(EXCLUDED.author, substack_subscriptions.author),
            last_synced_at = CURRENT_TIMESTAMP
        RETURNING id::text AS id, user_id::text AS user_id, feed_url, site_url, title, author, active, last_synced_at
        """,
        {
            "user_id": user_id,
            "feed_url": feed_url,
            "site_url": parsed.site_url,
            "title": parsed.title,
            "author": parsed.author,
        },
    )
    sub = dict(rows[0])
    concepts = await load_user_concepts_with_mastery(pg, neo4j, user_id)
    for entry in parsed.entries:
        matches, score = match_entry_to_concepts(
            entry.title, entry.summary, entry.excerpt_markdown, concepts
        )
        await pg.execute_update(
            """
            INSERT INTO substack_feed_articles
                (subscription_id, user_id, article_url, dedupe_key, publication_name, author,
                 title, summary, excerpt_markdown, published_at, matched_concepts, relevance_score)
            VALUES
                (CAST(:sub_id AS uuid), CAST(:user_id AS uuid), :article_url, :dedupe_key,
                 :pub_name, :author, :title, :summary, :excerpt_markdown, :published_at,
                 CAST(:matched_concepts AS jsonb), :relevance_score)
            ON CONFLICT (user_id, dedupe_key) DO UPDATE
            SET matched_concepts = EXCLUDED.matched_concepts,
                relevance_score = EXCLUDED.relevance_score
            """,
            {
                "sub_id": sub["id"],
                "user_id": user_id,
                "article_url": entry.url,
                "dedupe_key": entry.dedupe_key,
                "pub_name": sub["title"],
                "author": entry.author or sub.get("author"),
                "title": entry.title,
                "summary": entry.summary,
                "excerpt_markdown": entry.excerpt_markdown,
                "published_at": entry.published_at,
                "matched_concepts": json.dumps(matches),
                "relevance_score": score,
            },
        )
    return {"subscription": sub, "articles_synced": len(parsed.entries)}


@router.get("")
async def list_substack_subscriptions(
    user: dict = Depends(get_current_user),
    pg: PostgresClient = Depends(get_postgres_client),
):
    rows = await pg.execute_query(
        """
        SELECT id::text AS id, feed_url, site_url, title, author, active, last_synced_at, created_at
        FROM substack_subscriptions
        WHERE user_id = CAST(:user_id AS uuid) AND active = TRUE
        ORDER BY created_at DESC
        """,
        {"user_id": str(user["id"])},
    )
    return {"subscriptions": [dict(r) for r in rows]}


@router.delete("/{subscription_id}")
async def delete_substack_subscription(
    subscription_id: UUID,
    user: dict = Depends(get_current_user),
    pg: PostgresClient = Depends(get_postgres_client),
):
    rows = await pg.execute_insert(
        """
        DELETE FROM substack_subscriptions
        WHERE id = CAST(:sub_id AS uuid) AND user_id = CAST(:user_id AS uuid)
        RETURNING id::text AS id
        """,
        {"sub_id": str(subscription_id), "user_id": str(user["id"])},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"deleted": True}


@router.post("/sync")
async def sync_all_substack_subscriptions(
    user: dict = Depends(get_current_user),
    pg: PostgresClient = Depends(get_postgres_client),
    neo4j: Neo4jClient = Depends(get_neo4j_client),
):
    user_id = str(user["id"])
    subs = await pg.execute_query(
        """
        SELECT id::text AS id, user_id::text AS user_id, feed_url, site_url, title, author, active
        FROM substack_subscriptions
        WHERE user_id = CAST(:user_id AS uuid) AND active = TRUE
        """,
        {"user_id": user_id},
    )
    if not subs:
        return {"synced_subscriptions": 0, "articles_synced": 0}
    concepts = await load_user_concepts_with_mastery(pg, neo4j, user_id)
    total_articles = 0
    synced = 0
    for s in subs:
        try:
            _, count = await _sync_one_subscription(pg, dict(s), concepts)
            total_articles += count
            synced += 1
        except SubstackSyncError:
            continue
    return {"synced_subscriptions": synced, "articles_synced": total_articles}


@router.post("/articles/{article_id}/dismiss")
async def dismiss_substack_article(
    article_id: UUID,
    user: dict = Depends(get_current_user),
    pg: PostgresClient = Depends(get_postgres_client),
):
    rows = await pg.execute_insert(
        """
        UPDATE substack_feed_articles
        SET dismissed_at = CURRENT_TIMESTAMP
        WHERE id = CAST(:article_id AS uuid) AND user_id = CAST(:user_id AS uuid)
        RETURNING id::text AS id
        """,
        {"article_id": str(article_id), "user_id": str(user["id"])},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"dismissed": True}


# Generalized Links & Feeds router (/api/subscriptions/feeds) sharing the exact same handlers
feeds_router = APIRouter(prefix="/api/subscriptions/feeds", tags=["Link & Feed Subscriptions"])
for _route in router.routes:
    if isinstance(_route, APIRoute):
        _sub_path = _route.path[len(router.prefix):] if _route.path.startswith(router.prefix) else _route.path
        feeds_router.add_api_route(
            _sub_path,
            _route.endpoint,
            methods=list(_route.methods or ["GET"]),
            status_code=_route.status_code,
            name=f"feeds_{_route.name}",
        )
