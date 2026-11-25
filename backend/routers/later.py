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

from backend.auth.middleware import get_current_user
from backend.db.postgres_client import get_postgres_client
from backend.services.later import parse_later

logger = structlog.get_logger()
router = APIRouter(prefix="/api/later", tags=["Later"])


class LaterCreate(BaseModel):
    text: str = Field(default="", max_length=4000)
    url: Optional[str] = Field(default=None, max_length=2000)
    when: Optional[str] = Field(default=None, max_length=60, description='e.g. "tomorrow", "in 3 days"')
    tz: Optional[str] = Field(default=None, max_length=64, description="IANA time zone, e.g. Asia/Kolkata")
    source: Literal["typed", "voice", "share", "chat"] = "typed"


class Snooze(BaseModel):
    when: str = Field(default="tomorrow", max_length=60)
    tz: Optional[str] = Field(default=None, max_length=64)


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


@router.post("/{item_id}/done")
async def done_later(item_id: str, current_user: dict = Depends(get_current_user)):
    return await _update(item_id, str(current_user["id"]), "done_at = now()", {})


@router.post("/{item_id}/snooze")
async def snooze_later(item_id: str, body: Snooze, current_user: dict = Depends(get_current_user)):
    parsed = parse_later("", when=body.when, tz_name=body.tz)
    return await _update(item_id, str(current_user["id"]),
                         "show_at = :show_at, shown_at = NULL, when_phrase = :phrase",
                         {"show_at": parsed.show_at, "phrase": parsed.phrase or body.when})
