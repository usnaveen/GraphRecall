"""Article import (Substack, blogs): fetch -> extract -> dedupe -> ingest.

Previously this sent up to 200k characters of raw HTML to the LLM to find the article body. Now
extraction is deterministic (``backend/services/ingestion/article_extract.py``), which is free,
fast and testable. The LLM only cleans up when that extraction finds almost no text, and it sees
visible page text rather than markup.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from backend.services.ingestion.article_extract import (
    ArticleFetchError,
    ExtractedArticle,
    canonicalize_url,
    dedupe_key,
    extract_article,
    fetch_html,
    render_note,
)

logger = structlog.get_logger()

_FALLBACK_PROMPT = """You are given the visible text of a web page that contains an article.
Return only the article itself as clean Markdown: drop navigation, subscribe prompts, comments,
share buttons and footers. Keep headings, lists and code blocks. Do not summarize or add text.
Return JSON: {"title": "...", "author": "... or null", "markdown": "..."}"""


def url_hash(canonical_url: str) -> str:
    """Notes imported from a URL are deduplicated per user by their canonical URL."""
    return hashlib.sha256(f"url:{dedupe_key(canonical_url)}".encode()).hexdigest()


async def _existing_note(user_id: str, content_hash: str) -> Optional[str]:
    from backend.db.postgres_client import get_postgres_client

    pg = await get_postgres_client()
    rows = await pg.execute_query(
        "SELECT id FROM notes WHERE user_id = :user_id AND content_hash = :h LIMIT 1",
        {"user_id": user_id, "h": content_hash},
    )
    return str(rows[0]["id"]) if rows else None


async def _llm_clean(article: ExtractedArticle, html: str) -> ExtractedArticle:
    from bs4 import BeautifulSoup

    from backend.config.llm import get_chat_model

    soup = BeautifulSoup(html, "lxml")
    for junk in soup(["script", "style", "noscript", "svg"]):
        junk.decompose()
    text = soup.get_text("\n", strip=True)[:60_000]
    llm = get_chat_model(temperature=0.1)
    resp = await llm.ainvoke([SystemMessage(content=_FALLBACK_PROMPT), HumanMessage(content=text)])
    raw = resp.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1].removeprefix("json").strip()
    data = json.loads(raw)
    article.title = article.title or data.get("title")
    article.author = article.author or data.get("author")
    article.markdown = data.get("markdown") or article.markdown
    return article


async def process_article_url(url: str, user_id: str) -> dict:
    """Returns {title, url, ingestion_result, warnings, duplicate_note_id, error}."""
    from backend.graphs.ingestion_graph import run_ingestion

    result: dict = {"url": url, "warnings": [], "ingestion_result": {}, "error": None, "duplicate_note_id": None}

    # 1. Cheap duplicate check on the shared link, before any network fetch.
    shared = canonicalize_url(url)
    dup = await _existing_note(user_id, url_hash(shared))
    if dup:
        result.update(url=shared, duplicate_note_id=dup)
        return result

    # 2. Fetch safely and extract.
    try:
        final_url, html = await fetch_html(shared)
    except ArticleFetchError as e:
        result["error"] = f"Couldn't import that link: {e}"
        return result
    article = extract_article(html, final_url)

    # 3. The page's own canonical URL may differ from the shared link (custom domains, redirects).
    if dedupe_key(article.url) != dedupe_key(shared):
        dup = await _existing_note(user_id, url_hash(article.url))
        if dup:
            result.update(url=article.url, title=article.title, duplicate_note_id=dup)
            return result

    if article.needs_llm_fallback:
        logger.info("article_import: thin extraction, using LLM fallback", url=article.url,
                    chars=len(article.markdown))
        try:
            article = await _llm_clean(article, html)
        except Exception as e:  # keep what we have rather than failing the import
            logger.warning("article_import: LLM fallback failed", error=str(e))
    if len(article.markdown.strip()) < 80:
        result["error"] = "Couldn't find article text on that page."
        return result

    logger.info("article_import: extracted", url=article.url, substack=article.is_substack,
                paywalled=article.paywalled, chars=len(article.markdown))

    ingestion = await run_ingestion(
        content=render_note(article),
        title=article.title or article.url,
        user_id=user_id,
        skip_review=True,
        content_hash=url_hash(article.url),
        resource_type="article",
    )
    ingestion = dict(ingestion or {})
    ingestion["warnings"] = list(ingestion.get("warnings") or []) + article.warnings
    result.update(url=article.url, title=article.title, author=article.author,
                  published=article.published, ingestion_result=ingestion,
                  warnings=ingestion["warnings"])
    return result
