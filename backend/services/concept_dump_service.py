"""Concept Dump: bulk concepts → web research → teach cards + sources → feed."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

import structlog

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client

logger = structlog.get_logger()

try:
    from langchain_tavily import TavilySearch
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


async def _search_sources(topic: str, max_results: int = 4) -> list[dict[str, str]]:
    """Return [{title, url, snippet}] from Tavily, or Wikipedia fallback."""
    sources: list[dict[str, str]] = []
    if TAVILY_AVAILABLE:
        try:
            tavily = TavilySearch(max_results=max_results)
            raw = await tavily.ainvoke(f"{topic} explained site:wikipedia.org OR article tutorial")
            # langchain-tavily may return str or list/dict
            if isinstance(raw, str):
                sources.append({
                    "title": f"Research: {topic}",
                    "url": "",
                    "snippet": raw[:500],
                })
            elif isinstance(raw, dict):
                for item in raw.get("results", raw.get("organic", []))[:max_results]:
                    sources.append({
                        "title": str(item.get("title") or topic),
                        "url": str(item.get("url") or item.get("link") or ""),
                        "snippet": str(item.get("content") or item.get("snippet") or "")[:400],
                    })
            elif isinstance(raw, list):
                for item in raw[:max_results]:
                    if isinstance(item, dict):
                        sources.append({
                            "title": str(item.get("title") or topic),
                            "url": str(item.get("url") or ""),
                            "snippet": str(item.get("content") or item.get("snippet") or "")[:400],
                        })
        except Exception as e:
            logger.warning("concept_dump: Tavily failed", topic=topic, error=str(e))

    if not sources:
        wiki = topic.strip().replace(" ", "_")
        sources.append({
            "title": f"{topic} — Wikipedia",
            "url": f"https://en.wikipedia.org/wiki/{wiki}",
            "snippet": f"Open Wikipedia for an overview of {topic}.",
        })
    return sources


async def _ensure_concept(user_id: str, name: str) -> str:
    neo4j = await get_neo4j_client()
    concept_id = str(uuid.uuid4())
    norm = _normalize(name)
    rows = await neo4j.execute_query(
        """
        MERGE (c:Concept {name_normalized: $norm, user_id: $user_id})
        ON CREATE SET
            c.id = $id,
            c.name = $name,
            c.created_at = datetime(),
            c.source = 'concept_dump'
        ON MATCH SET
            c.name = coalesce(c.name, $name)
        RETURN c.id AS id
        """,
        {"norm": norm, "user_id": user_id, "id": concept_id, "name": name.strip()},
    )
    if rows and rows[0].get("id"):
        return str(rows[0]["id"])
    return concept_id


async def _save_note_and_cards(
    user_id: str,
    concept_id: str,
    name: str,
    sources: list[dict[str, str]],
) -> dict[str, Any]:
    pg = await get_postgres_client()
    note_id = str(uuid.uuid4())
    body_parts = [
        f"# {name}",
        "",
        f"Learning brief for **{name}** (Concept Dump).",
        "",
        "## Key idea",
        sources[0].get("snippet") or f"Study the linked articles to understand {name}.",
        "",
        "## Sources",
    ]
    for s in sources:
        if s.get("url"):
            body_parts.append(f"- [{s.get('title') or 'Source'}]({s['url']})")
        else:
            body_parts.append(f"- {s.get('title') or 'Source'}: {s.get('snippet','')[:200]}")
    content = "\n".join(body_parts)

    await pg.execute_insert(
        """
        INSERT INTO notes (id, user_id, title, content_text, created_at)
        VALUES (:id, :user_id, :title, :content_text, NOW())
        """,
        {
            "id": note_id,
            "user_id": user_id,
            "title": f"Learn: {name}",
            "content_text": content,
        },
    )

    # Teach cards
    cards = []
    front = f"What is {name}?"
    back = sources[0].get("snippet") or f"See sources for {name}."
    if sources and sources[0].get("url"):
        back = f"{back}\n\nRead: {sources[0]['url']}"
    card_id = str(uuid.uuid4())
    await pg.execute_insert(
        """
        INSERT INTO flashcards (id, user_id, concept_id, front_content, back_content, created_at, source)
        VALUES (:id, :user_id, :concept_id, :front, :back, NOW(), :source)
        """,
        {
            "id": card_id,
            "user_id": user_id,
            "concept_id": concept_id,
            "front": front,
            "back": back,
            "source": "concept_dump",
        },
    )
    cards.append({"id": card_id, "type": "flashcard", "front": front, "back": back})

    # Explain card in generated_content for feed diversity
    gen_id = str(uuid.uuid4())
    payload = {
        "title": name,
        "summary": sources[0].get("snippet") or f"Overview of {name}",
        "sources": sources,
    }
    await pg.execute_insert(
        """
        INSERT INTO generated_content (id, user_id, concept_id, content_type, content_json, created_at)
        VALUES (:id, :user_id, :concept_id, :content_type, :content_json, NOW())
        """,
        {
            "id": gen_id,
            "user_id": user_id,
            "concept_id": concept_id,
            "content_type": "showcase",
            "content_json": json.dumps(payload),
        },
    )
    cards.append({"id": gen_id, "type": "showcase", "front": name, "back": payload["summary"]})

    return {"note_id": note_id, "cards": cards}


async def dump_concepts(user_id: str, concepts: list[str]) -> dict[str, Any]:
    cleaned: list[str] = []
    seen = set()
    for raw in concepts:
        name = re.sub(r"\s+", " ", (raw or "").strip())
        if not name:
            continue
        key = _normalize(name)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(name)

    results = []
    for name in cleaned:
        try:
            sources = await _search_sources(name)
            concept_id = await _ensure_concept(user_id, name)
            saved = await _save_note_and_cards(user_id, concept_id, name, sources)
            results.append({
                "concept": name,
                "concept_id": concept_id,
                "status": "ok",
                "sources": sources,
                "note_id": saved["note_id"],
                "cards": saved["cards"],
            })
        except Exception as e:
            logger.error("concept_dump: failed item", concept=name, error=str(e))
            results.append({
                "concept": name,
                "status": "error",
                "error": str(e),
                "sources": [],
                "cards": [],
            })

    return {
        "status": "complete",
        "requested": len(concepts),
        "processed": len(cleaned),
        "succeeded": sum(1 for r in results if r.get("status") == "ok"),
        "results": results,
    }
