"""Article import: canonical URLs, Substack extraction, paywall warning, SSRF guard."""

import socket

import httpx
import pytest

from backend.services.ingestion import article_extract as ae

SUBSTACK_FREE = """<!doctype html><html><head>
<title>Why Retrieval Beats Fine-Tuning - Latent Notes</title>
<meta name="generator" content="Substack">
<meta property="og:site_name" content="Latent Notes">
<meta property="og:title" content="Why Retrieval Beats Fine-Tuning">
<link rel="canonical" href="https://latentnotes.substack.com/p/why-retrieval-beats-fine-tuning">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"NewsArticle",
 "headline":"Why Retrieval Beats Fine-Tuning","datePublished":"2026-10-02T09:00:00Z",
 "author":[{"@type":"Person","name":"Ada Writer"}],"isAccessibleForFree":true}</script>
</head><body>
<nav class="navbar">Home Archive About Subscribe</nav>
<article><div class="available-content"><div class="body markup">
<h2>The setup</h2>
<p>Fine-tuning bakes knowledge into <strong>weights</strong>. Retrieval keeps it in an index you can update.</p>
<div class="subscription-widget-wrap"><p>Subscribe to Latent Notes for free</p><button>Subscribe</button></div>
<ul><li>Freshness: update the index, not the model</li><li>Attribution: cite the chunk</li></ul>
<pre>score = cosine(q, d)</pre>
<p>That is most of the argument, and the rest of this post is evidence for it, with numbers from three
production systems that each ran both approaches side by side for a quarter.</p>
<p>A second paragraph long enough that the whole body clears the minimum-length threshold used to
decide whether deterministic extraction worked or whether the LLM fallback is needed at all.</p>
</div></div>
<div class="post-footer"><p>Share this post</p></div></article>
<div class="comments-section"><p>12 comments</p></div>
</body></html>"""

SUBSTACK_PAYWALLED = """<html><head><meta name="generator" content="Substack">
<meta property="og:title" content="Inside the Eval Harness">
<meta name="author" content="Bo Coder">
<link rel="canonical" href="https://evalweekly.substack.com/p/inside-the-eval-harness">
</head><body><article><div class="available-content"><div class="body markup">
<p>Free preview paragraph about evaluation harnesses, golden sets, and why you should version them like code.</p>
</div></div>
<div class="paywall"><h3>This post is for paid subscribers</h3><p>Already a paid subscriber? Sign in</p></div>
</article></body></html>"""

BLOG = """<html><head><title>Notes on HNSW</title>
<meta property="og:title" content="Notes on HNSW"><meta name="author" content="C. Indexer">
<meta property="article:published_time" content="2025-03-14">
</head><body><header>My Blog</header><main><article>
<h1>Notes on HNSW</h1><p>HNSW builds a layered proximity graph. Search starts at the top layer.</p>
<p>Each layer is sparser than the one below.</p></article></main><footer>(c) 2025</footer></body></html>"""


# ---- canonical URLs --------------------------------------------------------

@pytest.mark.parametrize("shared,expected", [
    ("https://open.substack.com/pub/latentnotes/p/why-retrieval?r=2abc&utm_campaign=post&utm_medium=web",
     "https://latentnotes.substack.com/p/why-retrieval"),
    ("https://latentnotes.substack.com/p/why-retrieval/?utm_source=share#footnote-1",
     "https://latentnotes.substack.com/p/why-retrieval/"),
    ("https://www.latentnotes.substack.com/p/x?triedRedirect=true", "https://latentnotes.substack.com/p/x"),
    ("https://example.com/post?id=7&utm_source=x", "https://example.com/post?id=7"),
])
def test_canonicalize(shared, expected):
    assert ae.canonicalize_url(shared) == expected


def test_dedupe_key_ignores_trailing_slash_and_share_form():
    a = ae.dedupe_key("https://open.substack.com/pub/latentnotes/p/why-retrieval?r=2abc")
    b = ae.dedupe_key("https://latentnotes.substack.com/p/why-retrieval/?utm_source=share")
    assert a == b == "https://latentnotes.substack.com/p/why-retrieval"


# ---- extraction ------------------------------------------------------------

def test_substack_free_post():
    art = ae.extract_article(SUBSTACK_FREE, "https://latentnotes.substack.com/p/why-retrieval-beats-fine-tuning?r=1")
    assert art.is_substack and not art.paywalled and art.warnings == []
    assert art.title == "Why Retrieval Beats Fine-Tuning"
    assert art.author == "Ada Writer"
    assert art.published.startswith("2026-10-02")
    assert art.url == "https://latentnotes.substack.com/p/why-retrieval-beats-fine-tuning"
    md = art.markdown
    assert "## The setup" in md and "**weights**" in md
    assert "- Freshness: update the index, not the model" in md
    assert "```\nscore = cosine(q, d)\n```" in md
    for junk in ("Subscribe", "Share this post", "12 comments", "Archive"):
        assert junk not in md
    assert not art.needs_llm_fallback


def test_substack_paywall_warns():
    art = ae.extract_article(SUBSTACK_PAYWALLED, "https://evalweekly.substack.com/p/inside-the-eval-harness")
    assert art.paywalled
    assert art.warnings == [ae.PAYWALL_WARNING]
    assert "Free preview paragraph" in art.markdown
    assert "paid subscribers" not in art.markdown
    assert "only the free preview" in ae.render_note(art)


def test_generic_blog():
    art = ae.extract_article(BLOG, "https://blog.example.com/hnsw")
    assert not art.is_substack and not art.paywalled
    assert art.title == "Notes on HNSW" and art.author == "C. Indexer"
    assert "layered proximity graph" in art.markdown
    assert "My Blog" not in art.markdown and "(c) 2025" not in art.markdown
    assert not art.markdown.startswith("# Notes on HNSW")  # title heading not duplicated in body
    assert art.needs_llm_fallback  # short page: the fallback would be tried


BLOG_WITH_CHROME = """<html><head><title>Long post</title></head><body>
<div class="site"><div id="nav"><ul><li>Home page link text here ok</li><li>Archive link for the whole blog</li></ul></div>
<div class="content"><h2>Section one</h2>
<p>This is the first real paragraph of the post and it has a reasonable amount of text in it.</p>
<p>This is the second real paragraph of the post, again with enough words to count as content.</p>
<p>And a third, because real articles have many paragraphs and the archive sidebar does not.</p></div>
<div class="sidebar"><ul><li>2019 archive entry with words</li><li>2020 archive entry with words</li></ul></div>
</div></body></html>"""


def test_generic_density_picks_content_not_chrome():
    art = ae.extract_article(BLOG_WITH_CHROME, "https://example.org/long/")
    assert "## Section one" in art.markdown and "third" in art.markdown
    assert "2019 archive entry" not in art.markdown and "Home page link" not in art.markdown


def test_render_note_header():
    art = ae.extract_article(SUBSTACK_FREE, "https://latentnotes.substack.com/p/why-retrieval-beats-fine-tuning")
    note = ae.render_note(art)
    assert note.startswith("Source: https://latentnotes.substack.com/p/why-retrieval-beats-fine-tuning\nAuthor: Ada Writer")
    assert "Published: 2026-10-02" in note and "Publication: Latent Notes" in note


# ---- SSRF guard ------------------------------------------------------------

@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "100.64.0.1", "0.0.0.0"])
def test_private_addresses_rejected(ip):
    assert not ae._is_public_ip(ip)


def test_public_address_allowed():
    assert ae._is_public_ip("93.184.216.34")


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "http://localhost:8000/admin", "http://127.0.0.1/"])
async def test_fetch_rejects_unsafe_urls(url):
    with pytest.raises(ae.ArticleFetchError):
        await ae.fetch_html(url)


@pytest.mark.asyncio
async def test_redirect_to_private_address_blocked(monkeypatch):
    import asyncio
    loop = asyncio.get_running_loop()

    async def getaddrinfo(host, port, **kw):
        ip = {"public.example": "93.184.216.34", "internal.example": "10.1.2.3"}[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(loop, "getaddrinfo", getaddrinfo)

    def handler(request):
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://internal.example/secret"})
        return httpx.Response(200, text="secret", headers={"content-type": "text/html"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        with pytest.raises(ae.ArticleFetchError, match="private"):
            await ae.fetch_html("https://public.example/post", client=client)


@pytest.mark.asyncio
async def test_fetch_follows_public_redirect_and_caps_type(monkeypatch):
    import asyncio
    loop = asyncio.get_running_loop()

    async def getaddrinfo(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
    monkeypatch.setattr(loop, "getaddrinfo", getaddrinfo)

    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        if request.url.path == "/pdf":
            return httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})
        return httpx.Response(200, text=BLOG, headers={"content-type": "text/html; charset=utf-8"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        final, html = await ae.fetch_html("https://blog.example.com/old", client=client)
        assert final == "https://blog.example.com/new" and "HNSW" in html
        with pytest.raises(ae.ArticleFetchError, match="not a web page"):
            await ae.fetch_html("https://blog.example.com/pdf", client=client)
