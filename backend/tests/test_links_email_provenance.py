"""Tests for generalized Links & Feeds normalization, signed email webhook, and concept provenance."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.email_ingest import (
    ingest_email_newsletter,
    sanitize_newsletter_html,
    split_newsletter_stories,
    verify_email_webhook_signature,
)
from backend.services.graph_hierarchy import load_concept_provenance
from backend.services.substack_sync import discover_feed_url_from_html, normalize_feed_url


def test_normalize_feed_url_supports_medium_youtube_substack_and_discovery():
    assert normalize_feed_url("@latentnotes") == ("https://latentnotes.substack.com/feed", "https://latentnotes.substack.com")
    assert normalize_feed_url("https://medium.com/@karpathy") == ("https://medium.com/feed/@karpathy", "https://medium.com/@karpathy")
    assert normalize_feed_url("https://www.youtube.com/channel/UC1234567890abcd") == (
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC1234567890abcd",
        "https://www.youtube.com/channel/UC1234567890abcd",
    )
    assert normalize_feed_url("https://lilianweng.github.io/index.xml")[0] == "https://lilianweng.github.io/index.xml"
    discovered = discover_feed_url_from_html(
        '<html><head><link rel="alternate" type="application/atom+xml" href="/atom.xml"></head></html>',
        "https://simonwillison.net/posts",
    )
    assert discovered == "https://simonwillison.net/atom.xml"


def test_email_hmac_and_newsletter_story_splitting():
    body = b'{"subject":"AI Weekly"}'
    sig = "sha256=" + hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    assert verify_email_webhook_signature(body, sig, "topsecret") is True
    assert verify_email_webhook_signature(body, sig, "wrong") is False
    assert verify_email_webhook_signature(body, None, "topsecret") is False
    assert verify_email_webhook_signature(body, sig, "") is False

    raw_html = (
        '<script>alert(1)</script>'
        '<img width="1" height="1" src="https://tracker.example/open.gif">'
        '<h2><a href="https://example.com/kv-cache?utm_source=mail">KV Cache tricks</a></h2>'
        '<p>Grouped-query attention cuts KV cache memory linearly with group size in inference.</p>'
        '<h2>Speculative Decoding</h2>'
        '<p>Draft models propose multiple tokens verified in one forward pass by the target model.</p>'
        '<p>Unsubscribe | Manage preferences</p>'
    )
    cleaned = sanitize_newsletter_html(raw_html)
    assert "<script" not in cleaned
    assert "tracker.example" not in cleaned
    stories = split_newsletter_stories("AI Weekly", html=raw_html, sender="digest@example.com")
    assert len(stories) == 2
    assert stories[0]["url"] == "https://example.com/kv-cache"
    assert "KV Cache tricks" in stories[0]["title"]


def test_email_webhook_endpoint_fails_closed_without_valid_hmac(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EMAIL_INGEST_WEBHOOK_SECRET", "webhook-secret")
    client = TestClient(app)
    resp = client.post("/api/ingest/email", json={"user_id": "u1", "subject": "Hi", "text": "Hello world"})
    assert resp.status_code == 401

    payload = json.dumps({
        "user_id": "11111111-1111-1111-1111-111111111111",
        "subject": "ML Digest",
        "sender": "ml@digest.dev",
        "text": "KV Cache optimization reduces transformer decoding latency.",
    }).encode("utf-8")
    sig = "sha256=" + hmac.new(b"webhook-secret", payload, hashlib.sha256).hexdigest()

    fake_pg = AsyncMock()
    fake_pg.execute_query = AsyncMock(return_value=[])
    fake_pg.execute_insert = AsyncMock(return_value=[{"id": "res-1"}])
    fake_neo = AsyncMock()
    fake_neo.execute_query = AsyncMock(return_value=[{"id": "c-kv", "name": "KV Cache", "domain": "Machine Learning"}])

    with patch("backend.routers.ingest_v2.get_postgres_client", AsyncMock(return_value=fake_pg)), patch(
        "backend.db.postgres_client.get_postgres_client", AsyncMock(return_value=fake_pg)
    ), patch(
        "backend.db.neo4j_client.get_neo4j_client", AsyncMock(return_value=fake_neo)
    ):
        ok_resp = client.post("/api/ingest/email", content=payload, headers={"X-GraphRecall-Signature": sig})
    assert ok_resp.status_code == 200
    data = ok_resp.json()
    assert data["stories_ingested"] == 1
    assert data["matched_concepts_total"] >= 1


@pytest.mark.asyncio
async def test_concept_provenance_aggregates_chronologically():
    class _Neo:
        async def execute_query(self, q, p=None):
            return [{"note_id": "n-1", "evidence_span": "Key-Value cache stores past keys and values."}]

    class _PG:
        async def execute_query(self, q, p=None):
            if "FROM notes" in q:
                return [{"id": "n-1", "title": "LLM Inference Notes", "source_url": None, "resource_type": "markdown", "created_at": datetime(2026, 11, 20, tzinfo=timezone.utc)}]
            if "FROM ingested_resources" in q:
                return [{
                    "source_kind": "email_newsletter",
                    "publication_name": "Latent Notes",
                    "title": "Serving Transformers Fast",
                    "source_url": "https://latent.example/kv",
                    "summary": "KV cache memory math",
                    "matched_concepts": [{"id": "c-kv", "name": "KV Cache"}],
                    "recorded_at": datetime(2026, 11, 25, tzinfo=timezone.utc),
                }]
            if "FROM knowledge_evidence" in q:
                return [{
                    "kind": "agent",
                    "signal": 0.6,
                    "source_id": "claude",
                    "detail": {"source": "claude", "context": "Discussed paged attention"},
                    "created_at": datetime(2026, 11, 26, tzinfo=timezone.utc),
                }]
            return []

    timeline = await load_concept_provenance("u1", "c-kv", concept_name="KV Cache", neo4j=_Neo(), pg=_PG())
    assert [t["kind"] for t in timeline] == ["agent", "email_newsletter", "markdown"]
