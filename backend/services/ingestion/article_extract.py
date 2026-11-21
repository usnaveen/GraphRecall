"""Fetch and extract a web article without sending raw HTML to an LLM.

What it handles:
- **Safe fetching (SSRF guard):** http(s) only. Every redirect hop is checked against private,
  loopback, link-local and reserved addresses. Size cap and timeout.
- **Canonical URLs:** strips tracking parameters and maps Substack's share-link forms
  (open.substack.com/pub/<pub>/p/<slug>, ?r=..&utm_..) to <pub>.substack.com/p/<slug>,
  so sharing the same post twice dedupes.
- **Metadata:** title, author and publish date from JSON-LD, OpenGraph and meta tags.
- **Body:** Substack's ``.available-content .body.markup`` when present, else <article>/<main>,
  converted to Markdown-ish text. Navigation, subscribe widgets, comments, footers and share
  buttons are removed.
- **Paywalls:** a Substack paywall marker means only the free preview was available, which the
  caller reports as a warning.

The LLM is only a fallback when deterministic extraction finds almost no text.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

MAX_BYTES = 5_000_000
MAX_REDIRECTS = 5
TIMEOUT_S = 20.0
MIN_BODY_CHARS = 400  # below this, extraction probably failed: fall back to the LLM
USER_AGENT = "GraphRecallBot/1.0 (+article import; respects paywalls)"

PAYWALL_WARNING = "paywalled preview: only the free part was ingested"

# Removed on every host: unambiguous trackers only.
_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid"}
# Short names like ``s``/``r``/``ref`` can select content on ordinary sites, so they're only
# stripped on Substack, where they're share/referral markers.
_SUBSTACK_TRACKING_PARAMS = {
    "r", "s", "triedredirect", "showwelcome", "isfreemail", "token", "publication_id", "post_id",
    "ref", "source", "sd",
}
_BOILERPLATE_SELECTORS = [
    "script", "style", "noscript", "iframe", "form", "button", "svg", "nav", "footer", "header",
    "aside", ".subscription-widget-wrap", ".subscribe-widget", ".subscription-widget",
    ".share-dialog", ".post-ufi", ".post-footer", ".comments-section", ".comments-page",
    ".footer", ".navbar", ".captioned-button-wrap", ".button-wrapper", ".paywall",
    ".paywall-jump", ".digest-post-embed", "[data-component-name='SubscribeWidget']",
    "[data-component-name='ButtonCreateButton']",
]


class ArticleFetchError(Exception):
    """The URL can't be fetched safely, or the response isn't an article."""


@dataclass
class ExtractedArticle:
    url: str                     # canonical
    title: Optional[str] = None
    author: Optional[str] = None
    published: Optional[str] = None  # ISO 8601 when known
    site_name: Optional[str] = None
    markdown: str = ""
    is_substack: bool = False
    paywalled: bool = False
    body_matched: bool = False  # a site-specific body selector (e.g. Substack's) found the article
    warnings: list[str] = field(default_factory=list)

    @property
    def needs_llm_fallback(self) -> bool:
        # A paywalled preview or a matched Substack body is short because the post is short or
        # locked; the LLM would only see the paywall and comments, so trust the extraction.
        if self.paywalled or self.body_matched:
            return False
        return len(self.markdown) < MIN_BODY_CHARS


# ----------------------------------------------------------------------------
# URLs
# ----------------------------------------------------------------------------

_OPEN_SUBSTACK = re.compile(r"^/pub/(?P<pub>[a-z0-9-]+)/p/(?P<slug>[^/?#]+)", re.I)


def canonicalize_url(url: str) -> str:
    """Normalize a shared article link: https, no fragment, no tracking parameters, Substack share forms."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    path = parts.path or "/"

    if host == "open.substack.com":
        m = _OPEN_SUBSTACK.match(path)
        if m:
            host, path = f"{m['pub'].lower()}.substack.com", f"/p/{m['slug']}"
    if host.startswith("www.") and host.endswith(".substack.com"):
        host = host[4:]

    drop = _TRACKING_PARAMS | (_SUBSTACK_TRACKING_PARAMS if host.endswith("substack.com") else set())
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in drop and not k.lower().startswith("utm_")
    ]
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    return urlunsplit((scheme, host + port, path, urlencode(query), ""))


def dedupe_key(url: str) -> str:
    """Canonical URL without a trailing slash: the same post shared two ways maps to one key."""
    c = canonicalize_url(url)
    parts = urlsplit(c)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def _is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


async def _assert_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ArticleFetchError("only http and https links can be imported")
    host = parts.hostname
    if not host:
        raise ArticleFetchError("the link has no host")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ArticleFetchError(f"can't resolve {host}") from e
    for *_, sockaddr in infos:
        if not _is_public_ip(sockaddr[0]):
            raise ArticleFetchError("links to private or local network addresses can't be imported")


async def fetch_html(url: str, *, client: Optional[httpx.AsyncClient] = None) -> tuple[str, str]:
    """GET with redirect-by-hand so every hop passes the SSRF check. Returns (final_url, html).

    The resolve-then-connect gap (DNS rebinding) remains: production should also block egress to
    private ranges at the network layer. The compose network for the API has no route to other
    internal services except Postgres and Neo4j, which require credentials.
    """
    own = client is None
    client = client or httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_S,
                                         headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"})
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            await _assert_public_url(current)
            async with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    loc = resp.headers.get("location")
                    if not loc:
                        raise ArticleFetchError("redirect without a location")
                    current = urljoin(current, loc)
                    continue
                if resp.status_code >= 400:
                    raise ArticleFetchError(f"the site answered HTTP {resp.status_code}")
                ctype = resp.headers.get("content-type", "")
                if ctype and "html" not in ctype and "xml" not in ctype:
                    raise ArticleFetchError(f"not a web page ({ctype.split(';')[0]})")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise ArticleFetchError("page is larger than 5 MB")
                encoding = resp.encoding or "utf-8"
                return current, body.decode(encoding, errors="replace")
        raise ArticleFetchError("too many redirects")
    finally:
        if own:
            await client.aclose()


# ----------------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------------

def _meta(soup: BeautifulSoup, *names: str) -> Optional[str]:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return None


def _json_ld(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            if isinstance(item, dict) and str(item.get("@type", "")).lower() in {
                "newsarticle", "article", "blogposting", "socialmediaposting", "reportagenewsarticle",
            }:
                return item
    return {}


def _author_from_ld(ld: dict) -> Optional[str]:
    author = ld.get("author")
    if isinstance(author, list):
        names = [a.get("name") for a in author if isinstance(a, dict) and a.get("name")]
        return ", ".join(names) or None
    if isinstance(author, dict):
        return author.get("name")
    if isinstance(author, str):
        return author
    return None


def _is_substack(soup: BeautifulSoup, url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith(".substack.com"):
        return True
    gen = _meta(soup, "generator") or ""
    if "substack" in gen.lower():
        return True
    return bool(soup.select_one("link[href*='substackcdn.com'], script[src*='substackcdn.com']"))


def _has_paywall(soup: BeautifulSoup) -> bool:
    if soup.select_one(".paywall, .paywall-jump, [data-testid='paywall'], .paywall-content"):
        return True
    ld = _json_ld(soup)
    if str(ld.get("isAccessibleForFree", "")).lower() == "false":
        return True
    return False


_HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


def _inline(node) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    inner = "".join(_inline(c) for c in node.children)
    if node.name in ("strong", "b") and inner.strip():
        return f"**{inner.strip()}**"
    if node.name in ("em", "i") and inner.strip():
        return f"*{inner.strip()}*"
    if node.name == "code":
        return f"`{inner}`"
    if node.name == "a" and node.get("href", "").startswith("http") and inner.strip():
        return f"[{inner.strip()}]({node['href']})"
    if node.name == "br":
        return "\n"
    return inner


def _to_markdown(root: Tag) -> str:
    out: list[str] = []

    def block(node) -> None:
        if isinstance(node, NavigableString):
            text = str(node).strip()
            if text:
                out.append(text)
            return
        if not isinstance(node, Tag):
            return
        name = node.name
        if name in _HEADINGS:
            text = node.get_text(" ", strip=True)
            if text:
                out.append(f"{_HEADINGS[name]} {text}")
        elif name == "p":
            text = re.sub(r"[ \t]+", " ", _inline(node)).strip()
            if text:
                out.append(text)
        elif name == "pre":
            out.append("```\n" + node.get_text().rstrip("\n") + "\n```")
        elif name == "blockquote":
            text = node.get_text("\n", strip=True)
            if text:
                out.append("\n".join(f"> {line}" for line in text.splitlines()))
        elif name in ("ul", "ol"):
            for i, li in enumerate(node.find_all("li", recursive=False), 1):
                bullet = f"{i}." if name == "ol" else "-"
                text = re.sub(r"\s+", " ", _inline(li)).strip()
                if text:
                    out.append(f"{bullet} {text}")
        elif name == "figure":
            cap = node.find("figcaption")
            if cap and cap.get_text(strip=True):
                out.append(f"*Figure: {cap.get_text(' ', strip=True)}*")
        elif name == "hr":
            out.append("---")
        elif name == "table":
            rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in node.find_all("tr")]
            rows = [r for r in rows if any(r)]
            if rows:
                out.append("| " + " | ".join(rows[0]) + " |")
                out.append("|" + " --- |" * len(rows[0]))
                out.extend("| " + " | ".join(r) + " |" for r in rows[1:])
        else:
            for child in node.children:
                block(child)

    block(root)
    return "\n\n".join(out).strip()


_BLOCK_TAGS = ("p", "pre", "li", "blockquote", "h2", "h3", "h4")


def _density_root(soup: BeautifulSoup) -> Optional[Tag]:
    """Readability-style pick: the container whose direct block children hold the most text.

    Scoring only direct children stops <body> (which contains everything) from always winning;
    the parent of the paragraphs wins instead.
    """
    best, best_score = None, 0
    for node in soup.find_all(["article", "main", "section", "div"]):
        score = 0
        for child in node.find_all(_BLOCK_TAGS, recursive=False):
            text = child.get_text(" ", strip=True)
            if len(text) > 25:
                score += len(text) + (40 if child.name == "p" else 0)
        cls = " ".join(node.get("class", [])).lower() + " " + (node.get("id") or "").lower()
        if any(w in cls for w in ("comment", "sidebar", "footer", "related", "nav", "menu", "widget")):
            score //= 4
        if score > best_score:
            best, best_score = node, score
    return best


def _body_root(soup: BeautifulSoup, substack: bool) -> tuple[Optional[Tag], bool]:
    """Returns (root, matched_site_selector)."""
    if substack:
        for sel in (".available-content .body.markup", ".body.markup", ".available-content"):
            node = soup.select_one(sel)
            if node and len(node.get_text(strip=True)) > 40:
                return node, True
    for sel in ("[itemprop='articleBody']", ".post-content", ".entry-content", ".article-body"):
        node = soup.select_one(sel)
        if node and len(node.get_text(strip=True)) > 200:
            return node, False
    dense = _density_root(soup)
    if dense is not None:
        return dense, False
    return soup.find("article") or soup.find("main") or soup.body, False


def extract_article(html: str, url: str) -> ExtractedArticle:
    """Deterministic extraction. Never raises on odd HTML; returns what it could find."""
    soup = BeautifulSoup(html, "lxml")
    substack = _is_substack(soup, url)
    paywalled = substack and _has_paywall(soup)
    ld = _json_ld(soup)

    canonical_tag = soup.find("link", rel="canonical")
    canonical = (canonical_tag.get("href") if canonical_tag else None) or _meta(soup, "og:url") or url
    canonical = canonicalize_url(urljoin(url, canonical))

    title = ld.get("headline") or _meta(soup, "og:title", "twitter:title") or (
        soup.title.get_text(strip=True) if soup.title else None)
    author = _author_from_ld(ld) or _meta(soup, "author", "article:author", "twitter:creator")
    published = ld.get("datePublished") or _meta(soup, "article:published_time", "date")
    site = _meta(soup, "og:site_name")
    if title and site and title.endswith(f" - {site}"):
        title = title[: -len(site) - 3].strip()

    root, matched = _body_root(soup, substack)
    if root is not None:
        for sel in _BOILERPLATE_SELECTORS:
            for junk in root.select(sel):
                junk.decompose()
    markdown = _to_markdown(root) if root is not None else ""
    # A first-line heading that just repeats the title is noise.
    if title and markdown.lstrip("# ").startswith(title):
        markdown = markdown.split("\n\n", 1)[1] if "\n\n" in markdown else ""

    art = ExtractedArticle(
        url=canonical, title=title, author=author, published=published, site_name=site,
        markdown=markdown, is_substack=substack, paywalled=paywalled, body_matched=matched,
    )
    if paywalled:
        art.warnings.append(PAYWALL_WARNING)
    return art


def render_note(article: ExtractedArticle) -> str:
    """The note text handed to ingestion: a short provenance header, then the body."""
    header = [f"Source: {article.url}"]
    if article.author:
        header.append(f"Author: {article.author}")
    if article.published:
        header.append(f"Published: {article.published[:10]}")
    if article.site_name:
        header.append(f"Publication: {article.site_name}")
    if article.paywalled:
        header.append("Note: paywalled post, only the free preview was available.")
    title = f"# {article.title}\n\n" if article.title else ""
    return "\n".join(header) + "\n\n" + title + article.markdown
