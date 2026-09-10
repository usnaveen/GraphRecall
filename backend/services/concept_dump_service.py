"""Concept Dump: bulk concepts → web research → teach cards + sources → feed.

Hardening (NAV-17 / BE-001):
- TTL cache + rate-limit for Tavily (cache key = normalized concept)
- Real Wikipedia summary extract fallback (REST API)
- Cheap LLM teach-card front/back via backend.config.llm when GOOGLE_API_KEY set
- Per-item errors are sanitized JSON strings (never HTML/stacks)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from typing import Any, Optional
from urllib.parse import quote

import httpx
import structlog

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client

logger = structlog.get_logger()

try:
    from langchain_tavily import TavilySearch
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS = int(os.getenv("CONCEPT_DUMP_CACHE_TTL_SECONDS", str(24 * 3600)))
_TAVILY_MIN_INTERVAL_SECONDS = float(os.getenv("CONCEPT_DUMP_TAVILY_MIN_INTERVAL_SECONDS", "0.75"))
_WIKI_USER_AGENT = os.getenv(
    "CONCEPT_DUMP_WIKI_USER_AGENT",
    "GraphRecall/1.0 (concept-dump; https://github.com/usnaveen/GraphRecall)",
)

# In-memory TTL cache: normalized_concept -> (expires_at_monotonic, sources)
_source_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_tavily_lock = asyncio.Lock()
_tavily_last_call_at = 0.0


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def user_facing_error(exc: BaseException, *, resource: str = "request") -> str:
    """Short JSON-safe message — never HTML, stacks, or raw exception dumps."""
    raw = str(exc) if exc is not None else ""
    lower = raw.lower()
    if (
        "<html" in lower
        or "<!doctype" in lower
        or "traceback" in lower
        or len(raw) > 280
        or "\n" in raw
    ):
        return f"Something went wrong loading {resource}. Please try again."
    cleaned = raw.strip() or f"Something went wrong loading {resource}."
    # Strip accidental angle-bracket tags
    cleaned = re.sub(r"<[^>]+>", "", cleaned).strip()
    return cleaned[:200]


def _cache_get(norm_key: str) -> Optional[list[dict[str, str]]]:
    entry = _source_cache.get(norm_key)
    if not entry:
        return None
    expires_at, sources = entry
    if time.monotonic() >= expires_at:
        _source_cache.pop(norm_key, None)
        return None
    return [dict(s) for s in sources]


def _cache_set(norm_key: str, sources: list[dict[str, str]]) -> None:
    _source_cache[norm_key] = (
        time.monotonic() + max(60, _CACHE_TTL_SECONDS),
        [dict(s) for s in sources],
    )


async def _rate_limit_tavily() -> None:
    """Enforce a minimum interval between Tavily calls (process-local)."""
    global _tavily_last_call_at
    async with _tavily_lock:
        now = time.monotonic()
        wait = _TAVILY_MIN_INTERVAL_SECONDS - (now - _tavily_last_call_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _tavily_last_call_at = time.monotonic()


def _normalize_tavily_raw(raw: Any, topic: str, max_results: int) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    if isinstance(raw, str):
        text = raw.strip()
        if text:
            sources.append({
                "title": f"Research: {topic}",
                "url": "",
                "snippet": text[:500],
            })
        return sources

    items: list = []
    if isinstance(raw, dict):
        items = raw.get("results") or raw.get("organic") or []
        if not isinstance(items, list):
            items = []
    elif isinstance(raw, list):
        items = raw

    for item in items[:max_results]:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("content") or item.get("snippet") or "")[:400]
        title = str(item.get("title") or topic)
        url = str(item.get("url") or item.get("link") or "")
        if not snippet and not url:
            continue
        sources.append({"title": title, "url": url, "snippet": snippet})
    return sources


async def _fetch_wikipedia_summary(topic: str) -> Optional[dict[str, str]]:
    """Fetch a real Wikipedia page summary extract (not a URL stub)."""
    title = topic.strip().replace(" ", "_")
    if not title:
        return None
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title, safe='_()')}"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": _WIKI_USER_AGENT,
                    "Accept": "application/json",
                },
            )
            if resp.status_code == 404:
                # Try search-like title (capitalize words)
                alt = "_".join(w.capitalize() for w in topic.strip().split())
                if alt != title:
                    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(alt, safe='_()')}"
                    resp = await client.get(
                        url,
                        headers={
                            "User-Agent": _WIKI_USER_AGENT,
                            "Accept": "application/json",
                        },
                    )
            if resp.status_code != 200:
                logger.warning(
                    "concept_dump: Wikipedia summary miss",
                    topic=topic,
                    status=resp.status_code,
                )
                return None
            data = resp.json()
            extract = (data.get("extract") or data.get("description") or "").strip()
            if not extract:
                return None
            page_url = (
                (data.get("content_urls") or {}).get("desktop", {}).get("page")
                or f"https://en.wikipedia.org/wiki/{quote(title, safe='_()')}"
            )
            display_title = str(data.get("title") or topic)
            return {
                "title": f"{display_title} — Wikipedia",
                "url": page_url,
                "snippet": extract[:800],
            }
    except Exception as e:
        logger.warning("concept_dump: Wikipedia fetch failed", topic=topic, error=str(e))
        return None


async def _wikipedia_fallback(topic: str) -> list[dict[str, str]]:
    wiki = await _fetch_wikipedia_summary(topic)
    if wiki:
        return [wiki]
    # Last-resort stub if Wikipedia itself is unreachable
    slug = topic.strip().replace(" ", "_")
    return [{
        "title": f"{topic} — Wikipedia",
        "url": f"https://en.wikipedia.org/wiki/{quote(slug, safe='_()')}",
        "snippet": f"Overview of {topic} (Wikipedia summary unavailable).",
    }]


async def _search_tavily(topic: str, max_results: int = 4) -> list[dict[str, str]]:
    if not TAVILY_AVAILABLE:
        return []
    if not os.getenv("TAVILY_API_KEY"):
        logger.info("concept_dump: TAVILY_API_KEY missing; skipping Tavily")
        return []
    try:
        await _rate_limit_tavily()
        tavily = TavilySearch(max_results=max_results)
        raw = await tavily.ainvoke(
            f"{topic} explained site:wikipedia.org OR article tutorial"
        )
        return _normalize_tavily_raw(raw, topic, max_results)
    except Exception as e:
        logger.warning("concept_dump: Tavily failed", topic=topic, error=str(e))
        return []


async def _search_sources(topic: str, max_results: int = 4) -> list[dict[str, str]]:
    """Return [{title, url, snippet}] from cache → Tavily → Wikipedia extract."""
    norm_key = _normalize(topic)
    cached = _cache_get(norm_key)
    if cached is not None:
        logger.info("concept_dump: cache hit", concept=norm_key)
        return cached

    sources = await _search_tavily(topic, max_results=max_results)
    if not sources:
        sources = await _wikipedia_fallback(topic)

    _cache_set(norm_key, sources)
    return sources


async def _llm_teach_card(
    name: str,
    sources: list[dict[str, str]],
) -> Optional[tuple[str, str]]:
    """Generate cheap front/back teach card via Gemini when API key is present."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from backend.config.llm import get_fast_model

        context_bits = []
        for s in sources[:3]:
            bit = (s.get("snippet") or "").strip()
            if bit:
                context_bits.append(bit)
            if s.get("url"):
                context_bits.append(f"Source: {s['url']}")
        context = "\n".join(context_bits)[:2500] or f"Topic: {name}"

        llm = get_fast_model(temperature=0.2, json_mode=True)
        prompt = (
            f'Create one concise teach flashcard for the concept "{name}".\n'
            "Return ONLY valid JSON with keys front and back.\n"
            "- front: a short question (max 120 chars)\n"
            "- back: a clear 1-3 sentence explanation a learner can memorize "
            "(max 400 chars; no markdown fences)\n\n"
            f"CONTEXT:\n{context}"
        )
        resp = await llm.ainvoke([
            SystemMessage(content="You write brief educational flashcards. Output JSON only."),
            HumanMessage(content=prompt),
        ])
        text = getattr(resp, "content", None) or str(resp)
        if isinstance(text, list):
            # Some providers return content blocks
            text = "".join(
                (b.get("text") if isinstance(b, dict) else str(b)) for b in text
            )
        text = str(text).strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        front = str(data.get("front") or "").strip()
        back = str(data.get("back") or "").strip()
        if not front or not back:
            return None
        return front[:200], back[:600]
    except Exception as e:
        logger.warning("concept_dump: LLM teach card failed", concept=name, error=str(e))
        return None


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
            body_parts.append(f"- {s.get('title') or 'Source'}: {s.get('snippet', '')[:200]}")
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

    # Teach cards — prefer cheap LLM backs when key present
    llm_card = await _llm_teach_card(name, sources)
    if llm_card:
        front, back = llm_card
    else:
        front = f"What is {name}?"
        back = sources[0].get("snippet") or f"See sources for {name}."
        if sources and sources[0].get("url"):
            back = f"{back}\n\nRead: {sources[0]['url']}"

    cards = []
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
                "error": user_facing_error(e, resource="concept dump"),
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


# Test helpers (clear cache between unit tests)
def _clear_source_cache_for_tests() -> None:
    _source_cache.clear()
