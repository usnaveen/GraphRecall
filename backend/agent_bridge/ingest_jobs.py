"""The background work behind the bridge's ingest tools (run as MCP Tasks, see tasks.py).

- ``ingest_link``: import one article link, exactly as the app's "Import link" does.
- ``save_learning_session``: at the end of a learning session the agent sends the topic, what the
  user learned, what they struggled with, the key details, and the resources they went through.
  This job writes one session note (so the session itself becomes part of the graph), imports each
  resource, then records knowledge evidence: learned concepts as a moderate signal, struggles as a
  low one, so the app schedules them sooner.

Unlike the feed tools, nothing here waits for approval: the user granted ``write:ingest`` for that.
Every note is still labelled as saved by their agent, and each import counts against the user's
normal daily ingest quota.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

import structlog

from backend.agent_bridge.tasks import Cancelled, tool_result

logger = structlog.get_logger()

Progress = Callable[[str], Awaitable[None]]
LEARNED_SIGNAL = 0.65
STRUGGLED_SIGNAL = 0.25
TRANSCRIPT_CAP = 30_000
# notes.resource_type is CHECK-constrained (notes, article, youtube, chat_conversation, ...); a session
# distilled from a conversation is a chat_conversation, and its title says "(learning session)".
SESSION_RESOURCE_TYPE = "chat_conversation"
_YOUTUBE_HOSTS = re.compile(r"(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$")
_OTHER_VIDEO_HOSTS = re.compile(r"(^|\.)(vimeo\.com|loom\.com|twitch\.tv)$")


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_youtube(url: str) -> bool:
    return bool(_YOUTUBE_HOSTS.search(_host(url)))


def is_video(url: str) -> bool:
    return is_youtube(url) or bool(_OTHER_VIDEO_HOSTS.search(_host(url)))


async def _charge(user_id: str) -> None:
    from backend.db.postgres_client import get_postgres_client
    from backend.services.quota import consume

    await consume(await get_postgres_client(), user_id, "ingest")


async def _after_ingest(user_id: str, ingestion: dict, title: str) -> None:
    """The same follow-ups the app's ingest routes run: re-embed retries and the feed event."""
    from backend.routers.ingest_v2 import _enqueue_note_ingested_event, _schedule_reembed_if_needed

    await _schedule_reembed_if_needed(ingestion, user_id)
    if ingestion.get("note_id") and ingestion.get("status", "completed") == "completed":
        await _enqueue_note_ingested_event(user_id, ingestion["note_id"], title, ingestion.get("concepts") or [])


async def _note_saved(user_id: str, note_id: Optional[str]) -> bool:
    """run_ingestion can report a note_id even when storing the note failed (it logs and carries on),
    so check the row exists before telling the agent it was imported."""
    if not note_id:
        return False
    from backend.db.postgres_client import get_postgres_client

    rows = await (await get_postgres_client()).execute_query(
        "SELECT 1 FROM notes WHERE id = CAST(:id AS UUID) AND user_id = CAST(:u AS UUID)", {"id": note_id, "u": user_id})
    return bool(rows)


def _concept_names(concepts: list[Any]) -> list[str]:
    out = []
    for c in concepts or []:
        name = c.get("name") if isinstance(c, dict) else c
        if name:
            out.append(str(name))
    return out


async def import_link(user_id: str, url: str) -> dict:
    """One resource -> an outcome dict. Never raises for per-link problems."""
    from backend.graphs.article_graph import process_article_url
    from backend.services.quota import QuotaExceeded

    if is_video(url) and not is_youtube(url):
        return {"url": url, "status": "skipped",
                "reason": "only YouTube videos can be imported; the link is listed in the session note"}
    try:
        await _charge(user_id)
    except QuotaExceeded as e:
        return {"url": url, "status": "skipped", "reason": f"daily import limit reached ({e.limit}/day)"}
    if is_youtube(url):
        return await import_youtube(user_id, url)
    try:
        res = await process_article_url(url, user_id=user_id)
    except Exception as e:
        logger.warning("agent_ingest: link failed", error=str(e))
        return {"url": url, "status": "error", "reason": "couldn't import this link"}
    if res.get("error"):
        return {"url": url, "status": "error", "reason": res["error"]}
    if res.get("duplicate_note_id"):
        return {"url": res.get("url") or url, "status": "duplicate", "note_id": res["duplicate_note_id"],
                "reason": "already in your library"}
    ing = res.get("ingestion_result") or {}
    title = res.get("title") or url
    if not await _note_saved(user_id, ing.get("note_id")):
        return {"url": url, "status": "error", "title": title, "reason": "the note couldn't be saved"}
    await _after_ingest(user_id, ing, title)
    return {"url": res.get("url") or url, "status": "imported", "note_id": ing.get("note_id"), "title": title,
            "concepts": _concept_names(ing.get("concepts"))[:30], "warnings": res.get("warnings") or []}


async def import_youtube(user_id: str, url: str) -> dict:
    """A YouTube resource: captions first, Gemini when captions are missing or blocked, link only last."""
    from backend.graphs.youtube_graph import import_video
    from backend.services.ingestion.youtube import YouTubeError

    try:
        res = await import_video(user_id, url)
    except YouTubeError as e:
        return {"url": url, "status": "error", "reason": str(e)}
    except Exception as e:
        logger.warning("agent_ingest: video failed", error=str(e))
        return {"url": url, "status": "error", "reason": "couldn't import this video"}
    out = {"url": res.get("url") or url, "note_id": res.get("note_id"), "title": res.get("title"),
           "transcript_source": res.get("transcript_source"), "warnings": res.get("warnings") or []}
    if res.get("status_reason") == "completed_duplicate":
        return {**out, "status": "duplicate", "reason": "already in your library"}
    if res.get("status") == "stored":
        return {**out, "status": "link_only", "reason": "no transcript could be had; only the link was saved"}
    if not await _note_saved(user_id, res.get("note_id")):
        return {**out, "status": "error", "reason": "the note couldn't be saved"}
    return {**out, "status": "imported", "concepts": _concept_names(res.get("concepts"))[:30]}


async def run_ingest_link(user_id: str, url: str, progress: Progress) -> dict:
    await progress(f"Reading {url}")
    out = await import_link(user_id, url)
    return tool_result(out, is_error=out["status"] in ("error", "skipped", "link_only"))


def render_session_note(topic: str, summary: str, learned: list[str], struggled: list[dict],
                        resources: list[dict], transcript: Optional[str], agent_name: str) -> tuple[str, bool]:
    """Markdown for the session note. Returns (markdown, transcript_was_cut)."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"# {topic}", "", f"_Learning session saved by your agent ({agent_name}) on {day}._", ""]
    if learned:
        lines += ["## What I learned", ""] + [f"- {c}" for c in learned] + [""]
    if struggled:
        lines += ["## What I struggled with", ""]
        lines += [f"- **{s['concept']}**" + (f": {s['why']}" if s.get("why") else "") for s in struggled] + [""]
    if summary.strip():
        lines += ["## Key details", "", summary.strip(), ""]
    if resources:
        lines += ["## Resources", ""]
        for r in resources:
            label = r.get("title") or r["url"]
            lines.append(f"- [{label}]({r['url']})" + (f": {r['note']}" if r.get("note") else ""))
        lines.append("")
    cut = False
    if transcript and transcript.strip():
        text = transcript.strip()
        cut = len(text) > TRANSCRIPT_CAP
        lines += ["## Conversation (excerpt)" if cut else "## Conversation", "", text[:TRANSCRIPT_CAP], ""]
    return "\n".join(lines), cut


async def run_learning_session(user_id: str, knowledge: Any, *, agent_name: str, topic: str, summary: str,
                               learned: list[str], struggled: list[dict], resources: list[dict],
                               transcript: Optional[str], progress: Progress) -> dict:
    note: dict[str, Any] = {"status": "skipped"}
    outcomes: list[dict] = []
    try:
        return await _learning_session(user_id, knowledge, agent_name, topic, summary, learned, struggled,
                                       resources, transcript, progress, note, outcomes)
    except Cancelled:
        saved = (["the session note"] if note.get("status") == "imported" else []) + \
            [f"{sum(1 for o in outcomes if o['status'] == 'imported')} of {len(resources)} resources"]
        raise Cancelled("Cancelled; already saved: " + ", ".join(saved))


async def _learning_session(user_id: str, knowledge: Any, agent_name: str, topic: str, summary: str,
                            learned: list[str], struggled: list[dict], resources: list[dict],
                            transcript: Optional[str], progress: Progress, note: dict, outcomes: list) -> dict:
    from backend.graphs.ingestion_graph import run_ingestion
    from backend.services.quota import QuotaExceeded

    warnings: list[str] = []

    # 1. The session note first, so its concepts exist when the evidence below looks them up.
    await progress("Saving the session note")
    md, cut = render_session_note(topic, summary, learned, struggled, resources, transcript, agent_name)
    if cut:
        warnings.append(f"the conversation was longer than {TRANSCRIPT_CAP:,} characters; only the start was saved")
    try:
        await _charge(user_id)
        title = f"{topic} (learning session)"
        ing = dict(await run_ingestion(content=md, title=title, user_id=user_id, skip_review=True,
                                       content_hash=hashlib.sha256(f"session:{md}".encode()).hexdigest(),
                                       resource_type=SESSION_RESOURCE_TYPE) or {})
        if await _note_saved(user_id, ing.get("note_id")):
            await _after_ingest(user_id, ing, title)
            note.update(status="imported", note_id=ing.get("note_id"), title=title,
                        concepts=_concept_names(ing.get("concepts"))[:50])
        else:
            note.update(status="error", title=title, reason="the session note couldn't be saved")
    except QuotaExceeded as e:
        note.update(status="skipped", reason=f"daily import limit reached ({e.limit}/day)")

    # 2. Each resource, one at a time (each is a full ingest with LLM extraction).
    for i, r in enumerate(resources, 1):
        await progress(f"Reading {i} of {len(resources)}: {r.get('title') or r['url']}"[:300])
        outcomes.append({**({"title": r["title"]} if r.get("title") else {}), **await import_link(user_id, r["url"])})

    # 3. Knowledge evidence. Struggles are a low signal, so the app reviews them sooner.
    await progress("Recording what you learned and struggled with")
    evidence = {"learned": [], "struggled": [], "not_in_graph": []}
    for kind, items, signal in (("learned", [{"concept": c, "why": None} for c in learned], LEARNED_SIGNAL),
                                ("struggled", struggled, STRUGGLED_SIGNAL)):
        for s in items:
            ctx = (f"struggled with this in a session on {topic}" + (f": {s['why']}" if s.get("why") else "")
                   if kind == "struggled" else f"learned in a session on {topic}")
            try:
                rec = await knowledge.record_exposure(user_id, s["concept"], ctx[:600], source="agent_session",
                                                      confidence=signal, create_if_missing=False)
                (evidence[kind] if rec.get("concept_id") else evidence["not_in_graph"]).append(rec.get("concept") or s["concept"])
            except Exception as e:
                logger.warning("agent_ingest: evidence failed", error=str(e))
                evidence["not_in_graph"].append(s["concept"])

    imported = sum(1 for o in outcomes if o["status"] == "imported")
    payload = {"topic": topic, "session_note": note, "resources": outcomes, "evidence": evidence,
               "summary": f"saved the session note and imported {imported} of {len(resources)} resources",
               "warnings": warnings}
    return tool_result(payload, is_error=note["status"] != "imported" and imported == 0)
