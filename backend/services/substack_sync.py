"""Native Substack / RSS publication sync and Knowledge-Graph concept matching.

Allows users to subscribe to Substack publications (by handle, post URL, or RSS feed URL),
safely fetches & parses new essays (blocking SSRF and XML entity expansion), scores each
essay against the user's Neo4j Concept graph (prioritizing shaky concepts < 0.4 mastery),
and turns top unread essays into first-class Substack Reading Cards in ``/api/feed``.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

import httpx
import structlog

from backend.models.feed_schemas import FeedItem, FeedItemType
from backend.services.ingestion.article_extract import canonicalize_url

logger = structlog.get_logger()

# Full-text Substack feeds (e.g. Ahead of AI) run to several MB; still capped and streamed.
MAX_FEED_BYTES = 8 * 1024 * 1024  # 8 MiB RSS cap
MAX_ITEMS_PER_SYNC = 15
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_HANDLE_RE = re.compile(r"^@?([a-zA-Z0-9][a-zA-Z0-9_-]{1,62})$")


class SubstackSyncError(ValueError):
    pass


_YT_CHANNEL_RE = re.compile(r"^/channel/(UC[a-zA-Z0-9_-]{10,})", re.I)
_FEED_LINK_RE = re.compile(
    r"<link\b(?=[^>]*\brel=['\"]?[^'\">]*\balternate\b)"
    r"(?=[^>]*\btype=['\"]?application/(?:rss|atom)\+xml)"
    r"[^>]*\bhref=['\"]([^'\"]+)['\"][^>]*>",
    re.I,
)


def discover_feed_url_from_html(html: str, base_url: str) -> Optional[str]:
    """Extract an alternate RSS/Atom feed link from a web page's HTML head."""
    if not html:
        return None
    m = _FEED_LINK_RE.search(html[:65536])
    if not m:
        return None
    href = unescape(m.group(1).strip())
    return urljoin(base_url, href) if href else None


def normalize_feed_url(raw: str) -> tuple[str, str]:
    """Normalize a Substack handle, Medium profile/pub, YouTube channel, blog URL, or RSS URL -> (feed_url, site_url)."""
    val = (raw or "").strip()
    if not val:
        raise SubstackSyncError("Publication URL or feed handle is required")

    m = _HANDLE_RE.match(val)
    if m and "." not in val and "/" not in val:
        sub = m.group(1).lower()
        site = f"https://{sub}.substack.com"
        return f"{site}/feed", site

    if not val.startswith(("http://", "https://")):
        val = "https://" + val

    parsed = urlparse(val)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise SubstackSyncError("Invalid publication URL")

    if host == "open.substack.com":
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "pub":
            site = f"https://{parts[1].lower()}.substack.com"
            return f"{site}/feed", site

    if host == "substack.com" and parsed.path.startswith("/@"):
        handle = parsed.path.split("/")[1].lstrip("@").lower()
        if handle:
            site = f"https://{handle}.substack.com"
            return f"{site}/feed", site

    # Medium profiles and publications
    if host in {"medium.com", "www.medium.com"}:
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            if parts[0] == "feed" and len(parts) >= 2:
                return f"https://medium.com/feed/{parts[1]}", f"https://medium.com/{parts[1]}"
            target = parts[0]
            return f"https://medium.com/feed/{target}", f"https://medium.com/{target}"

    # YouTube channel feeds (no YouTube Data API key needed for public channel RSS)
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path.startswith("/feeds/videos.xml") and parsed.query:
            return f"https://www.youtube.com{parsed.path}?{parsed.query}", "https://www.youtube.com"
        yt_m = _YT_CHANNEL_RE.match(parsed.path)
        if yt_m:
            cid = yt_m.group(1)
            return (
                f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
                f"https://www.youtube.com/channel/{cid}",
            )

    if host.startswith("www.") and host.endswith(".substack.com"):
        host = host[4:]

    port_suffix = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
    site = f"{scheme}://{host}{port_suffix}"
    path = parsed.path.rstrip("/")
    if path.endswith(("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml", ".xml", ".atom", ".rss")):
        return f"{site}{path}", site
    if path:
        return f"{site}{path}/feed", f"{site}{path}"
    return f"{site}/feed", site


def normalize_substack_feed_url(raw: str) -> tuple[str, str]:
    """Backwards-compatible alias for ``normalize_feed_url``."""
    return normalize_feed_url(raw)


def assert_public_url(url: str) -> None:
    """SSRF guard: reject loopback, private, link-local, and cloud-metadata addresses."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip()
    if not host or parsed.scheme not in {"http", "https"}:
        raise SubstackSyncError("Only public http(s) feed URLs are allowed")
    if host.lower() in {"localhost", "metadata.google.internal"}:
        raise SubstackSyncError("Private or local hosts are not allowed")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise SubstackSyncError(f"Could not resolve host {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise SubstackSyncError("Feed host resolves to a non-public IP address")


def _strip_html(raw_html: str, max_chars: int = 1200) -> str:
    if not raw_html:
        return ""
    # Preserve paragraph breaks cleanly for reader excerpts
    cleaned = re.sub(r"</(p|div|h[1-6]|li|blockquote)>", "\n\n", raw_html, flags=re.I)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.I)
    cleaned = unescape(_TAG_RE.sub(" ", cleaned))
    paragraphs = [_WS_RE.sub(" ", p).strip() for p in cleaned.split("\n\n")]
    paragraphs = [p for p in paragraphs if p]
    out = "\n\n".join(paragraphs)
    if len(out) > max_chars:
        return out[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return out


def _parse_pub_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


@dataclass
class ParsedSubstackEntry:
    title: str
    url: str
    dedupe_key: str
    summary: str
    excerpt_markdown: str
    author: Optional[str] = None
    published_at: Optional[datetime] = None


@dataclass
class ParsedSubstackFeed:
    title: str
    site_url: str
    author: Optional[str] = None
    entries: list[ParsedSubstackEntry] = field(default_factory=list)


def parse_rss_or_atom(xml_bytes: bytes, fallback_site_url: str) -> ParsedSubstackFeed:
    """Safely parse RSS 2.0 or Atom XML (rejects DTD / entity declarations to prevent XXE)."""
    if len(xml_bytes) > MAX_FEED_BYTES:
        raise SubstackSyncError("Feed XML exceeds the 8 MiB safety limit")
    head = xml_bytes[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise SubstackSyncError("XML DTD/ENTITY declarations are rejected for security")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise SubstackSyncError("Feed did not return valid RSS/Atom XML") from exc

    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    root_name = _local(root.tag)
    entries: list[ParsedSubstackEntry] = []

    if root_name == "rss" or root.find("channel") is not None:
        ch = root.find("channel")
        if ch is None:
            ch = root
        pub_title = (ch.findtext("title") or "").strip() or urlparse(fallback_site_url).hostname or "Substack"
        site_url = (ch.findtext("link") or "").strip() or fallback_site_url
        pub_author = None
        for child in ch:
            if _local(child.tag) in {"creator", "author", "managingeditor"} and (child.text or "").strip():
                pub_author = child.text.strip()
                break

        for item in ch.findall("item")[:MAX_ITEMS_PER_SYNC]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            canon_url = canonicalize_url(link)
            desc_html = item.findtext("description") or ""
            encoded_html = ""
            author = pub_author
            for child in item:
                lname = _local(child.tag)
                if lname == "encoded" and (child.text or "").strip():
                    encoded_html = child.text or ""
                elif lname in {"creator", "author"} and (child.text or "").strip():
                    author = child.text.strip()
            summary = _strip_html(desc_html or encoded_html, max_chars=340)
            excerpt = _strip_html(encoded_html or desc_html, max_chars=1400)
            pub_dt = _parse_pub_date(item.findtext("pubDate"))
            dedupe = hashlib.sha256(canon_url.lower().encode("utf-8")).hexdigest()
            entries.append(
                ParsedSubstackEntry(
                    title=title[:500],
                    url=canon_url,
                    dedupe_key=dedupe,
                    summary=summary or title,
                    excerpt_markdown=excerpt or summary or title,
                    author=author[:200] if author else None,
                    published_at=pub_dt,
                )
            )
        return ParsedSubstackFeed(title=pub_title[:300], site_url=site_url, author=pub_author, entries=entries)

    if root_name == "feed":
        pub_title = ""
        site_url = fallback_site_url
        pub_author = None
        raw_entries = []
        for child in root:
            lname = _local(child.tag)
            if lname == "title" and (child.text or "").strip():
                pub_title = child.text.strip()
            elif lname == "link":
                rel = (child.attrib.get("rel") or "alternate").lower()
                href = (child.attrib.get("href") or "").strip()
                if rel == "alternate" and href:
                    site_url = href
            elif lname == "author":
                for sub in child:
                    if _local(sub.tag) == "name" and (sub.text or "").strip():
                        pub_author = sub.text.strip()
            elif lname == "entry":
                raw_entries.append(child)

        for entry in raw_entries[:MAX_ITEMS_PER_SYNC]:
            title = ""
            link = ""
            summary_raw = ""
            content_raw = ""
            pub_str = None
            author = pub_author
            for child in entry:
                lname = _local(child.tag)
                if lname == "title" and (child.text or "").strip():
                    title = child.text.strip()
                elif lname == "link" and not link:
                    href = (child.attrib.get("href") or "").strip()
                    rel = (child.attrib.get("rel") or "alternate").lower()
                    if href and rel in {"alternate", ""}:
                        link = href
                elif lname == "summary" and (child.text or "").strip():
                    summary_raw = child.text
                elif lname == "content" and (child.text or "").strip():
                    content_raw = child.text
                elif lname in {"published", "updated"} and not pub_str and (child.text or "").strip():
                    pub_str = child.text.strip()
                elif lname == "author":
                    for sub in child:
                        if _local(sub.tag) == "name" and (sub.text or "").strip():
                            author = sub.text.strip()
            if not title or not link:
                continue
            canon_url = canonicalize_url(link)
            summary = _strip_html(summary_raw or content_raw, max_chars=340)
            excerpt = _strip_html(content_raw or summary_raw, max_chars=1400)
            dedupe = hashlib.sha256(canon_url.lower().encode("utf-8")).hexdigest()
            entries.append(
                ParsedSubstackEntry(
                    title=title[:500],
                    url=canon_url,
                    dedupe_key=dedupe,
                    summary=summary or title,
                    excerpt_markdown=excerpt or summary or title,
                    author=author[:200] if author else None,
                    published_at=_parse_pub_date(pub_str),
                )
            )
        return ParsedSubstackFeed(
            title=(pub_title or urlparse(fallback_site_url).hostname or "Substack")[:300],
            site_url=site_url,
            author=pub_author,
            entries=entries,
        )

    raise SubstackSyncError("Unrecognized XML feed root; expected RSS <rss> or Atom <feed>")


async def fetch_feed_xml(feed_url: str, transport: Optional[httpx.AsyncBaseTransport] = None) -> bytes:
    if transport is None:
        assert_public_url(feed_url)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(12.0),
        follow_redirects=True,
        max_redirects=4,
        transport=transport,
        headers={"User-Agent": "GraphRecallFeedSync/1.0 (+https://graphrecall.app)"},
    ) as client:
        resp = await client.get(feed_url)
        if resp.status_code >= 400:
            raise SubstackSyncError(f"Publication RSS returned HTTP {resp.status_code}")
        if transport is None:
            assert_public_url(str(resp.url))
        return resp.content


def match_entry_to_concepts(
    title: str,
    summary: str,
    excerpt: str,
    user_concepts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], float]:
    """Match an essay against the user's concepts, prioritizing shaky concepts (< 0.4 mastery)."""
    haystack = f"{title} {summary} {excerpt[:700]}".lower()
    hay_words = set(re.findall(r"[a-z0-9][a-z0-9+#.-]{1,}", haystack))
    matches: list[tuple[float, dict[str, Any]]] = []

    for c in user_concepts:
        cname = str(c.get("name") or "").strip()
        if len(cname) < 3:
            continue
        clower = cname.lower()
        hit = False
        if " " in clower or "-" in clower:
            hit = clower in haystack
        else:
            hit = clower in hay_words
        if not hit:
            continue

        mastery = c.get("mastery")
        reviewed = bool(c.get("reviewed"))
        if reviewed and mastery is not None and mastery < 0.4:
            state = "shaky"
            weight = 2.0
        elif reviewed and mastery is not None and mastery >= 0.7:
            state = "strong"
            weight = 1.15
        else:
            state = "seen"
            weight = 1.35

        in_title = 0.6 if clower in title.lower() else 0.0
        matches.append(
            (
                weight + in_title,
                {
                    "id": str(c["id"]),
                    "name": cname,
                    "state": state,
                    "domain": c.get("domain") or "General",
                },
            )
        )

    matches.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
    top = [m for _, m in matches[:4]]
    if not top:
        return [], 0.35
    score = min(1.95, 0.55 + sum(w for w, _ in matches[:3]) * 0.28)
    return top, round(score, 4)


async def load_user_concepts_with_mastery(pg_client: Any, neo4j_client: Any, user_id: str) -> list[dict[str, Any]]:
    neo_rows = await neo4j_client.execute_query(
        """
        MATCH (c:Concept)
        WHERE c.user_id = $user_id
        RETURN c.id AS id, c.name AS name, c.domain AS domain
        LIMIT 800
        """,
        {"user_id": user_id},
    )
    prof_rows = await pg_client.execute_query(
        """
        SELECT concept_id, score, COALESCE(total_reviews, repetition_count, 0) AS review_count
        FROM proficiency_scores
        WHERE user_id = CAST(:user_id AS uuid)
        """,
        {"user_id": user_id},
    )
    prof_map = {str(r["concept_id"]): r for r in prof_rows}
    out = []
    for r in neo_rows:
        cid = str(r.get("id") or "")
        if not cid:
            continue
        pr = prof_map.get(cid)
        out.append(
            {
                "id": cid,
                "name": r.get("name") or "",
                "domain": r.get("domain") or "General",
                "mastery": float(pr["score"]) if pr and pr.get("score") is not None else None,
                "reviewed": bool(pr and (pr.get("review_count") or 0) > 0),
            }
        )
    return out


def build_reason_line(publication_name: str, matched_concepts: list[dict[str, Any]]) -> str:
    if not matched_concepts:
        return f"New essay from {publication_name} in your reading subscriptions."
    shaky = [m["name"] for m in matched_concepts if m.get("state") == "shaky"]
    if shaky:
        joined = ", ".join(shaky[:2])
        return f"Reinforces your shaky recall on {joined} with fresh writing from {publication_name}."
    names = ", ".join(m["name"] for m in matched_concepts[:2])
    return f"Connects directly to {names} in your knowledge graph."


def article_row_to_feed_item(row: dict[str, Any]) -> FeedItem:
    raw_matches = row.get("matched_concepts") or []
    if isinstance(raw_matches, str):
        try:
            raw_matches = json.loads(raw_matches)
        except Exception:
            raw_matches = []
    matches = list(raw_matches) if isinstance(raw_matches, list) else []
    concept_ids = [str(m["id"]) for m in matches if isinstance(m, dict) and m.get("id")]
    pub = row.get("publication_name") or "Substack"
    author = row.get("author")
    domain = matches[0].get("domain") if matches and isinstance(matches[0], dict) else "Reading"
    media = _media_kind(row["article_url"])

    return FeedItem(
        id=f"substack:{row['id']}",
        item_type=FeedItemType.AGENT_CURATED,
        concept_id=concept_ids[0] if concept_ids else None,
        concept_name=matches[0].get("name") if matches and isinstance(matches[0], dict) else None,
        domain=domain,
        priority_score=float(row.get("relevance_score") or 1.25),
        content={
            "title": row["title"],
            "summary": row["summary"],
            "excerpt_markdown": row.get("excerpt_markdown") or row["summary"],
            "reason": build_reason_line(pub, matches),
            "source_url": row["article_url"],
            "source_kind": media["source_kind"],
            "item_kind": media["item_kind"],
            "video_id": media.get("video_id"),
            "thumbnail_url": media.get("thumbnail_url"),
            "publication_name": pub,
            "author": author,
            "substack_article_id": str(row["id"]),
            "ingested": row.get("ingested_note_id") is not None,
            "matched_concepts": matches,
            "concept_ids": concept_ids,
            "provenance": {
                "curated_by": "feed_subscription",
                "label": f"{media['label']} · {pub}",
            },
        },
    )


def _media_kind(url: str) -> dict[str, Any]:
    """Videos from YouTube get a thumbnail and play in the YouTube app; everything else is an article."""
    import re as _re
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    video_id = None
    if host.endswith("youtube.com"):
        video_id = (parse_qs(parsed.query).get("v") or [None])[0]
        if not video_id:
            m = _re.match(r"^/(?:shorts|embed|live)/([A-Za-z0-9_-]{6,})", parsed.path or "")
            video_id = m.group(1) if m else None
    elif host == "youtu.be":
        video_id = (parsed.path or "/").strip("/").split("/")[0] or None
    if video_id:
        return {
            "item_kind": "video",
            "source_kind": "youtube",
            "label": "YouTube",
            "video_id": video_id,
            "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        }
    if host.endswith("substack.com") or "substack" in host:
        return {"item_kind": "article", "source_kind": "substack", "label": "Substack"}
    if host.endswith("medium.com"):
        return {"item_kind": "article", "source_kind": "article", "label": "Medium"}
    return {"item_kind": "article", "source_kind": "article", "label": host.removeprefix("www.") or "Article"}


async def list_substack_feed_items(
    pg_client: Any,
    user_id: str,
    domains: Optional[list[str]] = None,
    limit: int = 3,
) -> list[FeedItem]:
    rows = await pg_client.execute_query(
        """
        SELECT a.id, a.article_url, a.publication_name, a.author, a.title, a.summary,
               a.excerpt_markdown, a.matched_concepts, a.relevance_score, a.ingested_note_id
        FROM substack_feed_articles a
        JOIN substack_subscriptions s ON s.id = a.subscription_id
        WHERE a.user_id = CAST(:user_id AS uuid)
          AND s.user_id = CAST(:user_id AS uuid)
          AND s.active = TRUE
          AND a.dismissed_at IS NULL
        ORDER BY a.relevance_score DESC, COALESCE(a.published_at, a.created_at) DESC
        LIMIT :limit
        """,
        {"user_id": user_id, "limit": max(1, min(limit * 8, 40))},
    )
    ranked = [article_row_to_feed_item(dict(r)) for r in rows]
    # Mix the kinds (a video, then an article, …), each in relevance order, so the feed isn't
    # all articles from one prolific newsletter.
    by_kind: dict[str, list[FeedItem]] = {}
    for it in ranked:
        by_kind.setdefault(it.content.get("item_kind") or "article", []).append(it)
    items = []
    queues = [by_kind[k] for k in ("video", "article") if k in by_kind]
    while any(queues):
        for q in queues:
            if q:
                items.append(q.pop(0))
    if domains:
        wanted = set(domains)
        items = [
            it for it in items
            if any(
                isinstance(m, dict) and m.get("domain") in wanted
                for m in (it.content.get("matched_concepts") or [])
            )
        ]
    return items[:limit]
