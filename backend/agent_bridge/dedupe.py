"""Helpers that make propose_feed_items idempotent."""

from __future__ import annotations

import hashlib
import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = re.compile(r"^(utm_[a-z]+|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|s|source)$", re.I)


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Canonical form for dedupe: lowercase scheme/host, no fragment, no tracking params,
    sorted query, no trailing slash. Returns None for empty/invalid input."""
    if not is_safe_http_url(url):
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return None
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not _TRACKING_PARAMS.match(k)
    )
    path = parts.path.rstrip("/") or ""
    # http/https are treated as the same resource.
    return urlunsplit(("https", host, path, urlencode(query), ""))


def is_safe_http_url(url: Optional[str]) -> bool:
    """True only for absolute http(s) URLs with a host. Rejects javascript:, data:,
    vbscript:, file:, protocol-relative and control-character tricks."""
    if not url or not isinstance(url, str):
        return False
    if any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in url.strip()) or "\\" in url:
        return False
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return parts.scheme.lower() in {"http", "https"} and bool(parts.hostname)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_dedupe_key(source_url: Optional[str], title: str, summary: str) -> str:
    norm = normalize_url(source_url)
    if norm:
        return _sha("url:" + norm)
    content = " ".join(f"{title}\n{summary}".lower().split())
    return _sha("content:" + content)
