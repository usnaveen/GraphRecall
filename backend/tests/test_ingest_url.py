"""/api/v2/ingest/url end to end on a scratch Postgres: import, duplicate share, paywall warning, 422.

The network fetch and the LLM ingestion are stubbed; dedupe runs against the real notes table.
"""

import uuid

import pytest
from fastapi import HTTPException

from backend.services.ingestion import article_extract as ae
from backend.tests.test_article_extract import SUBSTACK_FREE, SUBSTACK_PAYWALLED
from backend.tests.test_migrate import scratch_db  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def env(scratch_db, monkeypatch):  # noqa: F811
    from backend.db import migrate as M
    from backend.routers import ingest_v2

    pg, _ = scratch_db
    await M.migrate(pg)
    email = f"url-{uuid.uuid4().hex[:6]}@example.invalid"
    user = (await pg.execute_query("INSERT INTO users (email) VALUES (:e) RETURNING *", {"e": email}))[0]

    async def get_pg():
        return pg
    monkeypatch.setattr("backend.db.postgres_client.get_postgres_client", get_pg)

    pages = {}

    async def fake_fetch(url, client=None):
        if url not in pages:
            raise ae.ArticleFetchError("links to private or local network addresses can't be imported")
        return url, pages[url]
    monkeypatch.setattr("backend.graphs.article_graph.fetch_html", fake_fetch)

    calls = []

    async def fake_ingestion(*, content, title, user_id, content_hash, **kw):
        calls.append({"content": content, "title": title, "hash": content_hash})
        nid = str(uuid.uuid4())
        await pg.execute_update(
            "INSERT INTO notes (id, user_id, title, content_text, content_hash) "
            "VALUES (CAST(:n AS uuid), CAST(:u AS uuid), :t, :c, :h)",
            {"n": nid, "u": user_id, "t": title, "c": content, "h": content_hash})
        return {"note_id": nid, "status": "completed", "concepts": [], "warnings": []}
    import importlib, sys

    importlib.import_module("backend.graphs.ingestion_graph")
    # backend.graphs re-exports a compiled graph named `ingestion_graph`, which shadows the module
    # in dotted-path lookups, so patch the module object itself.
    monkeypatch.setattr(sys.modules["backend.graphs.ingestion_graph"], "run_ingestion", fake_ingestion)

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(ingest_v2, "_schedule_reembed_if_needed", noop)
    monkeypatch.setattr(ingest_v2, "_enqueue_note_ingested_event", noop)
    return ingest_v2, user, pages, calls


async def test_import_then_duplicate_share(env):
    ingest_v2, user, pages, calls = env
    pages["https://latentnotes.substack.com/p/why-retrieval-beats-fine-tuning"] = SUBSTACK_FREE

    first = await ingest_v2.ingest_url(ingest_v2.IngestUrlRequest(
        url="https://open.substack.com/pub/latentnotes/p/why-retrieval-beats-fine-tuning?r=2x&utm_medium=ios"),
        current_user=user)
    assert first.note_id and first.status_reason == "completed" and first.warnings == []
    assert calls[0]["title"] == "Why Retrieval Beats Fine-Tuning"
    assert calls[0]["content"].startswith("Source: https://latentnotes.substack.com/p/why-retrieval-beats-fine-tuning")

    # same post, shared from the web with a trailing slash: no fetch, no second ingestion
    again = await ingest_v2.ingest_url(ingest_v2.IngestUrlRequest(
        url="https://latentnotes.substack.com/p/why-retrieval-beats-fine-tuning/?utm_source=share"), current_user=user)
    assert again.status_reason == "completed_duplicate" and again.note_id == first.note_id
    assert "already in your library" in again.warnings[0]
    assert len(calls) == 1


async def test_paywall_warning_reaches_response(env):
    ingest_v2, user, pages, _ = env
    pages["https://evalweekly.substack.com/p/inside-the-eval-harness"] = SUBSTACK_PAYWALLED
    out = await ingest_v2.ingest_url(ingest_v2.IngestUrlRequest(
        url="https://evalweekly.substack.com/p/inside-the-eval-harness"), current_user=user)
    assert out.warnings == [ae.PAYWALL_WARNING]


async def test_unsafe_link_is_422(env):
    ingest_v2, user, _, calls = env
    with pytest.raises(HTTPException) as e:
        await ingest_v2.ingest_url(ingest_v2.IngestUrlRequest(url="http://169.254.169.254/latest"), current_user=user)
    assert e.value.status_code == 422 and "private or local" in e.value.detail
    assert calls == []
