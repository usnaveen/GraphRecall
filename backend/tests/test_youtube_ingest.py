"""YouTube import: id parsing, transcript shaping, captions -> Gemini -> link-only order, and the endpoint.

No network: captions, oEmbed and Gemini are stubbed. The endpoint tests run on a scratch Postgres so
dedupe and the link-only fallback hit the real notes table.
"""

import uuid

import pytest
from fastapi import HTTPException

from backend.services.ingestion import youtube as yt
from backend.tests.test_migrate import scratch_db  # noqa: F401  (fixture)

VID = "aircAruvnKk"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://www.youtube.com/watch?v={VID}&t=42s&list=PLx",
    f"youtube.com/watch?feature=share&v={VID}",
    f"https://m.youtube.com/watch?v={VID}",
    f"https://youtu.be/{VID}?si=abc",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"https://www.youtube.com/live/{VID}?feature=share",
    f"https://music.youtube.com/watch?v={VID}",
    VID,
])
def test_parse_video_id_variants(url):
    assert yt.parse_video_id(url) == VID


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/@3blue1brown",
    "https://www.youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi",
    f"https://evil.example/watch?v={VID}",
    "https://www.youtube.com/watch?v=short",
    "",
])
def test_parse_video_id_rejects_non_videos(url):
    with pytest.raises(yt.YouTubeError):
        yt.parse_video_id(url)


def test_stamp_formats():
    assert yt.stamp(4.2) == "[00:04]"
    assert yt.stamp(605) == "[10:05]"
    assert yt.stamp(3725) == "[1:02:05]"


def test_paragraphs_group_by_minute_and_drop_noise():
    snippets = [(0.0, "[Music]"), (4.2, "This is a 3."), (6.0, "It's sloppily written\nand rendered"),
                (59.0, "still first minute"), (64.5, "second paragraph ♪♪"), (130.0, "third")]
    text = yt.paragraphs_from_snippets(snippets)
    paras = text.split("\n\n")
    assert paras[0] == "[00:04] This is a 3. It's sloppily written and rendered still first minute"
    assert paras[1] == "[01:04] second paragraph"
    assert paras[2] == "[02:10] third"
    assert "Music" not in text


def test_render_note_names_the_source():
    v = yt.VideoTranscript(video_id=VID, url=yt.watch_url(VID), title="But what is a neural network?",
                           channel="3Blue1Brown", text="[00:04] hello " * 20, source="auto_captions")
    note = yt.render_note(v)
    assert note.startswith("# But what is a neural network?\n")
    assert f"Video: https://www.youtube.com/watch?v={VID}" in note
    assert "Channel: 3Blue1Brown" in note and "automatic captions" in note and "## Transcript" in note


LONG = "[00:00] " + "neurons and weights and biases " * 10


@pytest.fixture
def stubs(monkeypatch):
    state = {"captions": (LONG, "captions", "en", None), "gemini": None, "gemini_calls": 0}

    async def meta(vid, client=None):
        return {"title": "Neural networks", "channel": "3Blue1Brown"}

    async def caps(vid):
        return state["captions"]

    async def gem(vid, client=None):
        state["gemini_calls"] += 1
        return state["gemini"]
    monkeypatch.setattr(yt, "fetch_metadata", meta)
    monkeypatch.setattr(yt, "fetch_captions", caps)
    monkeypatch.setattr(yt, "transcribe_with_gemini", gem)
    return state


@pytest.mark.asyncio
async def test_captions_win_and_gemini_is_not_called(stubs):
    v = await yt.get_transcript(f"https://youtu.be/{VID}")
    assert v.ok and v.source == "captions" and v.title == "Neural networks" and v.warnings == []
    assert stubs["gemini_calls"] == 0


@pytest.mark.asyncio
async def test_blocked_captions_fall_back_to_gemini(stubs):
    stubs["captions"] = (None, None, None, "RequestBlocked")
    stubs["gemini"] = LONG
    v = await yt.get_transcript(VID)
    assert v.ok and v.source == "gemini" and "RequestBlocked" in v.warnings[0] and "Gemini" in v.warnings[0]


@pytest.mark.asyncio
async def test_nothing_available_is_honest(stubs):
    stubs["captions"] = (None, None, None, "TranscriptsDisabled")
    v = await yt.get_transcript(VID)
    assert not v.ok and v.source == "none" and "saved the link only" in v.warnings[0]


@pytest.mark.asyncio
async def test_non_english_captions_warn(stubs):
    stubs["captions"] = (LONG, "captions", "de", None)
    v = await yt.get_transcript(VID)
    assert v.source == "captions" and "'de'" in v.warnings[0]


@pytest.mark.asyncio
async def test_gemini_skipped_without_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert await yt.transcribe_with_gemini(VID) is None


# ---------------------------------------------------------------- endpoint, on a scratch Postgres

@pytest.fixture
async def env(scratch_db, monkeypatch, stubs):  # noqa: F811
    import importlib
    import sys

    from backend.db import migrate as M
    from backend.routers import ingest_v2

    pg, _ = scratch_db
    await M.migrate(pg)
    user = (await pg.execute_query("INSERT INTO users (email) VALUES (:e) RETURNING *",
                                   {"e": f"yt-{uuid.uuid4().hex[:6]}@example.invalid"}))[0]

    async def get_pg():
        return pg
    monkeypatch.setattr("backend.db.postgres_client.get_postgres_client", get_pg)
    monkeypatch.setattr(ingest_v2, "get_postgres_client", get_pg)

    calls = []

    async def fake_ingestion(*, content, title, user_id, content_hash, resource_type=None, **kw):
        calls.append({"content": content, "title": title, "hash": content_hash, "type": resource_type})
        nid = str(uuid.uuid4())
        await pg.execute_update(
            "INSERT INTO notes (id, user_id, title, content_text, content_hash, resource_type) "
            "VALUES (CAST(:n AS uuid), CAST(:u AS uuid), :t, :c, :h, :r)",
            {"n": nid, "u": user_id, "t": title, "c": content, "h": content_hash, "r": resource_type})
        return {"note_id": nid, "status": "completed", "concepts": [{"name": "Neuron"}], "concept_ids": ["c1"],
                "warnings": []}
    importlib.import_module("backend.graphs.ingestion_graph")
    monkeypatch.setattr(sys.modules["backend.graphs.ingestion_graph"], "run_ingestion", fake_ingestion)

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(ingest_v2, "_schedule_reembed_if_needed", noop)
    monkeypatch.setattr(ingest_v2, "_enqueue_note_ingested_event", noop)
    return ingest_v2, pg, user, calls, stubs


@pytest.mark.asyncio
async def test_endpoint_ingests_transcript_then_dedupes(env):
    ingest_v2, pg, user, calls, _ = env
    out = await ingest_v2.ingest_youtube_link(
        ingest_v2.IngestYoutubeRequest(url=f"https://youtu.be/{VID}?si=x"), current_user=user)
    assert out["status"] == "completed" and out["transcript_source"] == "captions"
    assert out["resource_type"] == "youtube" and out["url"] == f"https://www.youtube.com/watch?v={VID}"
    assert out["concept_ids"] == ["c1"] and calls[0]["type"] == "youtube" and "## Transcript" in calls[0]["content"]
    row = (await pg.execute_query("SELECT source_url FROM notes WHERE id = CAST(:i AS uuid)", {"i": out["note_id"]}))[0]
    assert row["source_url"] == out["url"]

    again = await ingest_v2.ingest_youtube_link(
        ingest_v2.IngestYoutubeRequest(url=f"https://www.youtube.com/watch?v={VID}&t=10"), current_user=user)
    assert again["status_reason"] == "completed_duplicate" and again["note_id"] == out["note_id"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_endpoint_stores_link_only_when_no_transcript(env):
    ingest_v2, pg, user, calls, stubs = env
    stubs["captions"] = (None, None, None, "TranscriptsDisabled")
    out = await ingest_v2.ingest_youtube_link(ingest_v2.IngestYoutubeRequest(url=VID), current_user=user)
    assert out["status"] == "stored" and out["transcript_source"] == "none" and calls == []
    assert "saved the link only" in out["warnings"][0]
    row = (await pg.execute_query("SELECT resource_type, content_text FROM notes WHERE id = CAST(:i AS uuid)",
                                  {"i": out["note_id"]}))[0]
    assert row["resource_type"] == "youtube" and row["content_text"].startswith("YouTube link:")


@pytest.mark.asyncio
async def test_endpoint_rejects_non_video_links(env):
    ingest_v2, _, user, calls, _ = env
    with pytest.raises(HTTPException) as e:
        await ingest_v2.ingest_youtube_link(
            ingest_v2.IngestYoutubeRequest(url="https://www.youtube.com/@3blue1brown"), current_user=user)
    assert e.value.status_code == 422 and calls == []
