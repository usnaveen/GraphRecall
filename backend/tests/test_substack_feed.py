"""Tests for native Substack / RSS feed sync, security guards, and Reels Feed card conversion."""

from __future__ import annotations

import pytest

from backend.models.feed_schemas import FeedItemType
from backend.services.substack_sync import (
    SubstackSyncError,
    article_row_to_feed_item,
    assert_public_url,
    match_entry_to_concepts,
    normalize_substack_feed_url,
    parse_rss_or_atom,
)

SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Systems &amp; Inference Weekly</title>
    <link>https://inferenceweekly.substack.com</link>
    <item>
      <title>Why Speculative Decoding Stalls When Rejection Sampling Drifts</title>
      <link>https://open.substack.com/pub/inferenceweekly/p/speculative-decoding-drift?r=abc&amp;utm_source=substack</link>
      <dc:creator>Ada Systems</dc:creator>
      <pubDate>Thu, 26 Nov 2026 10:00:00 GMT</pubDate>
      <description><![CDATA[<p>Draft models speed up KV cache reads, but rejection sampling collapses acceptance rates under temperature mismatch.</p>]]></description>
      <content:encoded><![CDATA[<p>Draft models speed up KV cache reads, but rejection sampling collapses acceptance rates under temperature mismatch.</p><p>Here is how verifier distributions stay exact without biasing token probabilities.</p>]]></content:encoded>
    </item>
  </channel>
</rss>
"""

SAMPLE_ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Consensus Notes</title>
  <link rel="alternate" href="https://consensus.example.com"/>
  <author><name>Grace Distributed</name></author>
  <entry>
    <title>Linearizability vs Serializability in Multi-Region Stores</title>
    <link rel="alternate" href="https://consensus.example.com/p/linearizability"/>
    <updated>2026-11-26T09:30:00Z</updated>
    <summary type="html">&lt;p&gt;Real-time ordering guarantees under network partitions.&lt;/p&gt;</summary>
  </entry>
</feed>
"""


def test_normalize_substack_feed_url_variants():
    assert normalize_substack_feed_url("latentnotes") == (
        "https://latentnotes.substack.com/feed",
        "https://latentnotes.substack.com",
    )
    assert normalize_substack_feed_url("@stratechery") == (
        "https://stratechery.substack.com/feed",
        "https://stratechery.substack.com",
    )
    assert normalize_substack_feed_url("https://open.substack.com/pub/inferenceweekly/p/post-1?r=2") == (
        "https://inferenceweekly.substack.com/feed",
        "https://inferenceweekly.substack.com",
    )
    assert normalize_substack_feed_url("https://substack.com/@adasystems") == (
        "https://adasystems.substack.com/feed",
        "https://adasystems.substack.com",
    )
    assert normalize_substack_feed_url("https://blog.example.com/rss.xml") == (
        "https://blog.example.com/rss.xml",
        "https://blog.example.com",
    )


def test_ssrf_and_xxe_guards():
    with pytest.raises(SubstackSyncError):
        assert_public_url("http://127.0.0.1:8000/feed")
    with pytest.raises(SubstackSyncError):
        assert_public_url("http://localhost/feed")

    xxe_payload = b"""<?xml version="1.0"?>
    <!DOCTYPE foo [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
    <rss><channel><title>&xxe;</title></channel></rss>
    """
    with pytest.raises(SubstackSyncError, match="DTD/ENTITY"):
        parse_rss_or_atom(xxe_payload, "https://example.substack.com")


def test_parse_rss_and_atom_and_shaky_concept_matching():
    rss = parse_rss_or_atom(SAMPLE_RSS, "https://inferenceweekly.substack.com")
    assert rss.title == "Systems & Inference Weekly"
    assert len(rss.entries) == 1
    entry = rss.entries[0]
    assert entry.url == "https://inferenceweekly.substack.com/p/speculative-decoding-drift"
    assert entry.author == "Ada Systems"
    assert "verifier distributions" in entry.excerpt_markdown

    atom = parse_rss_or_atom(SAMPLE_ATOM, "https://consensus.example.com")
    assert atom.title == "Consensus Notes"
    assert len(atom.entries) == 1
    assert atom.entries[0].author == "Grace Distributed"

    concepts = [
        {"id": "c-kv", "name": "KV Cache", "domain": "ML Systems", "mastery": 0.88, "reviewed": True},
        {"id": "c-rej", "name": "Rejection Sampling", "domain": "ML Systems", "mastery": 0.28, "reviewed": True},
        {"id": "c-raft", "name": "Raft", "domain": "Distributed Systems", "mastery": 0.90, "reviewed": True},
    ]
    matched, score = match_entry_to_concepts(entry.title, entry.summary, entry.excerpt_markdown, concepts)
    assert [m["name"] for m in matched] == ["Rejection Sampling", "KV Cache"]
    assert matched[0]["state"] == "shaky"
    assert score > 1.2

    card = article_row_to_feed_item(
        {
            "id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "article_url": entry.url,
            "publication_name": rss.title,
            "author": entry.author,
            "title": entry.title,
            "summary": entry.summary,
            "excerpt_markdown": entry.excerpt_markdown,
            "matched_concepts": matched,
            "relevance_score": score,
            "ingested_note_id": None,
        }
    )
    assert card.item_type == FeedItemType.AGENT_CURATED
    assert card.content["source_kind"] == "substack"
    assert card.content["publication_name"] == "Systems & Inference Weekly"
    assert "shaky recall on Rejection Sampling" in card.content["reason"]
