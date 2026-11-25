"""'Show me this later' captures: save now, resurface in the feed at the chosen time.

POST /api/later                 {text, url?, when?, tz?, source?}  -> parsed item
GET  /api/later/due             items whose time has come (marks them shown)
GET  /api/later                 upcoming + due, not done
POST /api/later/{id}/done       finished with it
POST /api/later/{id}/snooze     {when}  push it back
No LLM: the time phrase is parsed by backend/services/later.py.
"""
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.agent_v2.enqueue import enqueue_durable_job
from backend.auth.middleware import get_current_user
from backend.db.postgres_client import get_postgres_client
from backend.services.creative_cards import is_safe_http_url, plan_article_digest
from backend.services.later import parse_later

logger = structlog.get_logger()
router = APIRouter(prefix="/api/later", tags=["Later"])


class LaterCreate(BaseModel):
    text: str = Field(default="", max_length=4000)
    url: Optional[str] = Field(default=None, max_length=2000)
    when: Optional[str] = Field(default=None, max_length=60, description='e.g. "tomorrow", "in 3 days"')
    tz: Optional[str] = Field(default=None, max_length=64, description="IANA time zone, e.g. Asia/Kolkata")
    source: Literal["typed", "voice", "share", "chat", "agent"] = "typed"


class Snooze(BaseModel):
    when: str = Field(default="tomorrow", max_length=60)
    tz: Optional[str] = Field(default=None, max_length=64)


class DigestRequest(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2000)
    text: str = Field(default="", max_length=200000)
    title: Optional[str] = Field(default="", max_length=500)


_COLS = "id::text AS id, text, url, source, when_phrase, show_at, shown_at, created_at"


def _row(r: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}


@router.post("")
async def create_later(body: LaterCreate, current_user: dict = Depends(get_current_user)):
    url = (body.url or "").strip() or None
    if url and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must be http(s)")
    parsed = parse_later(body.text, when=body.when, tz_name=body.tz)
    text = parsed.text or (url or "")
    if not text:
        raise HTTPException(status_code=422, detail="Nothing to save: add some text or a link")
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        f"""
        INSERT INTO later_items (user_id, text, url, source, when_phrase, show_at)
        VALUES (CAST(:u AS uuid), :text, :url, :source, :phrase, :show_at)
        RETURNING {_COLS}
        """,
        {"u": str(current_user["id"]), "text": text, "url": url, "source": body.source,
         "phrase": parsed.phrase, "show_at": parsed.show_at},
    )
    return _row(rows[0])


@router.get("/due")
async def due_later(limit: int = Query(default=10, ge=1, le=50), current_user: dict = Depends(get_current_user)):
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        f"""
        UPDATE later_items SET shown_at = COALESCE(shown_at, now())
        WHERE id IN (
            SELECT id FROM later_items
            WHERE user_id = CAST(:u AS uuid) AND done_at IS NULL AND show_at <= now()
            ORDER BY show_at LIMIT :lim
        )
        RETURNING {_COLS}
        """,
        {"u": str(current_user["id"]), "lim": limit},
    )
    return {"items": [_row(r) for r in sorted(rows or [], key=lambda r: r["show_at"])]}


@router.get("")
async def list_later(current_user: dict = Depends(get_current_user)):
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        f"SELECT {_COLS} FROM later_items WHERE user_id = CAST(:u AS uuid) AND done_at IS NULL "
        "ORDER BY show_at LIMIT 200",
        {"u": str(current_user["id"])},
    )
    return {"items": [_row(r) for r in rows or []]}


async def _update(item_id: str, user_id: str, sql_set: str, params: dict) -> dict:
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        f"UPDATE later_items SET {sql_set} WHERE id::text = :id AND user_id = CAST(:u AS uuid) "
        f"AND done_at IS NULL RETURNING {_COLS}",
        {"id": item_id, "u": user_id, **params},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Item not found")
    return _row(rows[0])


async def _run_digest_and_enqueue(
    *,
    user_id: str,
    title: str,
    markdown_text: str,
    source_url: Optional[str],
    pg_client=None,
    item_id: Optional[str] = None,
) -> dict:
    plan = plan_article_digest(
        title=title,
        markdown_text=markdown_text,
        source_url=source_url,
    )
    plan_dict = plan.as_dict()
    queued_job_id: Optional[str] = None
    try:
        pg = pg_client if pg_client is not None else await get_postgres_client()
        if pg is not None:
            payload: dict = {
                "title": plan.title,
                "source_url": plan.source_url,
                "text": markdown_text[:20000],
                "plan": plan_dict,
            }
            if item_id is not None:
                payload["item_id"] = item_id
            job = await enqueue_durable_job(
                user_id,
                "article.digest",
                payload,
                pg_client=pg,
            )
            queued_job_id = job.id if job is not None else None
    except Exception as exc:  # noqa: BLE001 - best-effort enqueue must not break digest endpoint
        logger.warning("later.digest_enqueue_skipped", error=str(exc))

    return {
        "digested": True,
        "plan": plan_dict,
        "card_count": plan.total_cards,
        "diagram_count": len(plan.diagram_cards),
        "queued_job_id": queued_job_id,
    }


@router.post("/digest-url")
async def digest_url(body: DigestRequest, current_user: dict = Depends(get_current_user)):
    raw_url = (body.url or "").strip() if body.url is not None else ""
    if raw_url and not is_safe_http_url(raw_url):
        raise HTTPException(status_code=422, detail="url must be a valid http(s) URL")
    clean_url = raw_url or None
    markdown_text = body.text or ""
    if not clean_url and not markdown_text.strip():
        raise HTTPException(status_code=422, detail="Nothing to digest: add text or a valid http(s) url")
    title = (body.title or "").strip() or (clean_url or "")
    return await _run_digest_and_enqueue(
        user_id=str(current_user["id"]),
        title=title,
        markdown_text=markdown_text,
        source_url=clean_url,
    )


@router.post("/{item_id}/done")
async def done_later(item_id: str, current_user: dict = Depends(get_current_user)):
    return await _update(item_id, str(current_user["id"]), "done_at = now()", {})


@router.post("/{item_id}/digest")
async def digest_later(
    item_id: str,
    body: Optional[DigestRequest] = None,
    current_user: dict = Depends(get_current_user),
):
    if body is not None and body.url is not None and body.url.strip() and not is_safe_http_url(body.url.strip()):
        raise HTTPException(status_code=422, detail="url must be a valid http(s) URL")

    user_id = str(current_user["id"])
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        f"UPDATE later_items SET done_at = now() WHERE id::text = :id AND user_id = CAST(:u AS uuid) "
        f"AND done_at IS NULL RETURNING {_COLS}",
        {"id": item_id, "u": user_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Item not found")
    item = _row(rows[0])

    source_url = (
        body.url.strip()
        if body is not None and body.url is not None and body.url.strip()
        else item.get("url")
    )
    if source_url and not is_safe_http_url(source_url):
        raise HTTPException(status_code=422, detail="url must be a valid http(s) URL")

    markdown_text = (body.text if body is not None and body.text else item.get("text") or "")
    title = (
        body.title.strip()
        if body is not None and body.title is not None and body.title.strip()
        else (item.get("text") or source_url or "")[:120]
    )
    return await _run_digest_and_enqueue(
        user_id=user_id,
        title=title,
        markdown_text=markdown_text,
        source_url=source_url,
        pg_client=pg,
        item_id=item_id,
    )


@router.post("/{item_id}/snooze")
async def snooze_later(item_id: str, body: Snooze, current_user: dict = Depends(get_current_user)):
    parsed = parse_later("", when=body.when, tz_name=body.tz)
    return await _update(item_id, str(current_user["id"]),
                         "show_at = :show_at, shown_at = NULL, when_phrase = :phrase",
                         {"show_at": parsed.show_at, "phrase": parsed.phrase or body.when})
