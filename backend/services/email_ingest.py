"""Signed inbound email newsletter ingestion, HTML sanitization, and story splitting (Spec §2)."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Optional

from bs4 import BeautifulSoup

from backend.services.ingestion.article_extract import canonicalize_url
from backend.services.substack_sync import load_user_concepts_with_mastery, match_entry_to_concepts

_TRACKING_PIXEL_RE = re.compile(r"<img\b[^>]*(?:width=['\"]?1['\"]?|height=['\"]?1['\"]?)[^>]*>", re.I)
_UNSUB_LINE_RE = re.compile(
    r"(?:unsubscribe|manage preferences|view in browser|update your email settings|privacy policy).*$",
    re.I | re.M,
)


def verify_email_webhook_signature(
    raw_body: bytes,
    signature_header: Optional[str],
    secret: Optional[str],
) -> bool:
    """Constant-time HMAC-SHA256 verification. Fails closed when secret or header is missing."""
    if not secret or not signature_header:
        return False
    provided = signature_header.strip()
    if provided.lower().startswith("sha256="):
        provided = provided[7:].strip()
    if not provided:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided.lower())


def sanitize_newsletter_html(raw_html: str) -> str:
    """Strip unsafe scripts/styles, tracking pixels, and unsubscribe boilerplate from newsletter HTML."""
    if not raw_html:
        return ""
    cleaned = _TRACKING_PIXEL_RE.sub("", raw_html)
    soup = BeautifulSoup(cleaned, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "form", "svg"]):
        tag.decompose()
    return str(soup)


def _html_to_text(html_fragment: str) -> str:
    if not html_fragment:
        return ""
    soup = BeautifulSoup(html_fragment, "html.parser")
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", unescape(text))
    text = _UNSUB_LINE_RE.sub("", text).strip()
    return text


def _first_http_link(soup_nodes: list[Any]) -> Optional[str]:
    for node in soup_nodes:
        for a in node.find_all("a", href=True) if hasattr(node, "find_all") else []:
            href = (a.get("href") or "").strip()
            if href.startswith(("http://", "https://")) and "unsubscribe" not in href.lower():
                return canonicalize_url(href)
    return None


def split_newsletter_stories(
    subject: str,
    html: str = "",
    text: str = "",
    sender: str = "",
) -> list[dict[str, str]]:
    """Split a newsletter email into one or more coherent stories for card digestion."""
    sanitized = sanitize_newsletter_html(html) if html else ""
    stories: list[dict[str, str]] = []

    if sanitized:
        soup = BeautifulSoup(sanitized, "html.parser")
        headings = soup.find_all(["h2", "h3"])
        if len(headings) >= 2:
            for h in headings:
                title = re.sub(r"\s+", " ", h.get_text(" ", strip=True))
                if not title or "unsubscribe" in title.lower():
                    continue
                section_nodes = []
                for sib in h.next_siblings:
                    if getattr(sib, "name", None) in {"h2", "h3", "hr"}:
                        break
                    section_nodes.append(sib)
                sec_html = "".join(str(n) for n in section_nodes)
                body_text = _html_to_text(sec_html)
                if len(body_text) < 25:
                    continue
                link = None
                if h.find("a", href=True):
                    link = canonicalize_url(h.find("a", href=True)["href"])
                elif section_nodes:
                    link = _first_http_link(section_nodes)
                stories.append({
                    "title": title[:300],
                    "summary": body_text[:340],
                    "excerpt_markdown": body_text[:1800],
                    "url": link or "",
                    "sender": sender,
                })

    if not stories:
        plain = _html_to_text(sanitized) if sanitized else _UNSUB_LINE_RE.sub("", text or "").strip()
        if not plain and not subject:
            return []
        link = None
        if sanitized:
            soup = BeautifulSoup(sanitized, "html.parser")
            link = _first_http_link([soup])
        stories.append({
            "title": (subject or "Newsletter Note").strip()[:300],
            "summary": (plain or subject)[:340],
            "excerpt_markdown": (plain or subject)[:2000],
            "url": link or "",
            "sender": sender,
        })

    return stories[:12]


async def ingest_email_newsletter(
    pg: Any,
    neo4j: Any,
    user_id: str,
    *,
    subject: str,
    sender: str = "",
    publication_name: Optional[str] = None,
    html: str = "",
    text: str = "",
    message_id: Optional[str] = None,
    published_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Sanitize, split into stories, match against concepts, and persist to ``ingested_resources``."""
    stories = split_newsletter_stories(subject, html=html, text=text, sender=sender)
    concepts = await load_user_concepts_with_mastery(pg, neo4j, user_id)
    pub = (publication_name or sender or "Newsletter").strip()[:240]
    pub_dt = published_at or datetime.now(timezone.utc)

    saved: list[dict[str, Any]] = []
    matched_total = 0
    for idx, story in enumerate(stories):
        matches, score = match_entry_to_concepts(
            story["title"], story["summary"], story["excerpt_markdown"], concepts
        )
        matched_total += len(matches)
        dedupe_seed = story["url"] or f"{message_id or subject}:{idx}:{story['title']}"
        dedupe_key = hashlib.sha256(dedupe_seed.lower().encode("utf-8")).hexdigest()
        rows = await pg.execute_insert(
            """
            INSERT INTO ingested_resources
                (user_id, source_kind, source_url, dedupe_key, sender, publication_name,
                 title, summary, excerpt_markdown, matched_concepts, relevance_score,
                 digest_status, published_at)
            VALUES
                (CAST(:u AS uuid), 'email_newsletter', :url, :dk, :sender, :pub,
                 :title, :summary, :excerpt, CAST(:mc AS jsonb), :score, 'pending', :pub_dt)
            ON CONFLICT (user_id, dedupe_key) DO UPDATE
            SET matched_concepts = EXCLUDED.matched_concepts,
                relevance_score = EXCLUDED.relevance_score
            RETURNING id::text AS id
            """,
            {
                "u": user_id,
                "url": story["url"] or None,
                "dk": dedupe_key,
                "sender": sender[:200] if sender else None,
                "pub": pub,
                "title": story["title"],
                "summary": story["summary"],
                "excerpt": story["excerpt_markdown"],
                "mc": json.dumps(matches),
                "score": score,
                "pub_dt": pub_dt,
            },
        )
        rid = rows[0]["id"] if rows else dedupe_key
        saved.append({
            "id": rid,
            "title": story["title"],
            "source_url": story["url"] or None,
            "matched_concepts": matches,
            "relevance_score": score,
        })

    return {
        "status": "ingested",
        "publication_name": pub,
        "stories_ingested": len(saved),
        "matched_concepts_total": matched_total,
        "stories": saved,
    }
