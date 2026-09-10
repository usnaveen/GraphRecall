"""Unit tests for Concept Dump hardening (NAV-17 / BE-001)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services import concept_dump_service as cds


@pytest.fixture(autouse=True)
def _clear_cache():
    cds._clear_source_cache_for_tests()
    yield
    cds._clear_source_cache_for_tests()


def test_user_facing_error_strips_html_and_stacks():
    html = Exception("<!DOCTYPE html><html><body>Proxy error</body></html>")
    msg = cds.user_facing_error(html, resource="graph")
    assert "<html" not in msg.lower()
    assert "graph" in msg.lower()

    stack = Exception("Traceback (most recent call last):\n  File foo.py line 1\nBoom")
    msg2 = cds.user_facing_error(stack, resource="concept dump")
    assert "traceback" not in msg2.lower()
    assert "\n" not in msg2

    short = Exception("Neo4j unavailable")
    assert cds.user_facing_error(short, resource="graph") == "Neo4j unavailable"


def test_normalize_tavily_raw_dict_and_list():
    raw = {
        "results": [
            {"title": "A", "url": "https://a.example", "content": "alpha"},
            {"title": "B", "link": "https://b.example", "snippet": "beta"},
        ]
    }
    out = cds._normalize_tavily_raw(raw, "Topic", 4)
    assert len(out) == 2
    assert out[0]["url"] == "https://a.example"
    assert out[1]["snippet"] == "beta"

    out2 = cds._normalize_tavily_raw(
        [{"title": "C", "url": "https://c.example", "content": "gamma"}],
        "Topic",
        4,
    )
    assert out2[0]["snippet"] == "gamma"


@pytest.mark.asyncio
async def test_search_sources_uses_cache_by_normalized_concept(monkeypatch):
    calls = {"n": 0}

    async def fake_tavily(topic, max_results=4):
        calls["n"] += 1
        return [{"title": topic, "url": "https://ex", "snippet": "cached-body"}]

    monkeypatch.setattr(cds, "_search_tavily", fake_tavily)
    monkeypatch.setattr(
        cds,
        "_wikipedia_fallback",
        AsyncMock(side_effect=AssertionError("wiki should not run on tavily hit")),
    )

    a = await cds._search_sources("  Neural   Network ")
    b = await cds._search_sources("neural network")
    assert a[0]["snippet"] == "cached-body"
    assert b[0]["snippet"] == "cached-body"
    assert calls["n"] == 1  # second call served from TTL cache


@pytest.mark.asyncio
async def test_search_sources_falls_back_to_wikipedia_on_tavily_miss(monkeypatch):
    monkeypatch.setattr(cds, "_search_tavily", AsyncMock(return_value=[]))

    async def fake_wiki(topic):
        return [{
            "title": f"{topic} — Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Photosynthesis",
            "snippet": "Photosynthesis is a process used by plants.",
        }]

    monkeypatch.setattr(cds, "_wikipedia_fallback", fake_wiki)
    sources = await cds._search_sources("Photosynthesis")
    assert "plants" in sources[0]["snippet"]
    assert "wikipedia.org" in sources[0]["url"]


@pytest.mark.asyncio
async def test_fetch_wikipedia_summary_parses_extract(monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "title": "Gradient Descent",
                "extract": "Gradient descent is a first-order iterative optimization algorithm.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Gradient_descent"}},
            }

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setattr(cds.httpx, "AsyncClient", FakeClient)
    result = await cds._fetch_wikipedia_summary("Gradient Descent")
    assert result is not None
    assert "optimization" in result["snippet"]
    assert result["url"].endswith("Gradient_descent")


@pytest.mark.asyncio
async def test_llm_teach_card_skipped_without_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert await cds._llm_teach_card("X", [{"snippet": "y"}]) is None


@pytest.mark.asyncio
async def test_dump_item_error_is_sanitized(monkeypatch):
    async def boom_sources(name):
        raise RuntimeError("<html>Internal proxy blew up with a huge stack</html>")

    monkeypatch.setattr(cds, "_search_sources", boom_sources)
    out = await cds.dump_concepts("user-1", ["Bad Concept"])
    assert out["succeeded"] == 0
    err = out["results"][0]["error"]
    assert "<html" not in err.lower()
    assert "\n" not in err
