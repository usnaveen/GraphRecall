"""User-facing REST API for the agent bridge (Google-authenticated app user).

* Agent keys: create (plaintext shown once), list, revoke.
* Agent-curated feed items: list, approve, reject.
* "Ask my agent" queue: enqueue, list, get, stream status (SSE), cancel.

The agent itself talks to GraphRecall over MCP (``backend/agent_bridge/mcp_app.py``),
not through these routes.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.agent_bridge.keys import DEFAULT_SCOPES, InvalidScopeError, validate_scopes
from backend.agent_bridge.repository import REQUEST_TERMINAL
from backend.agent_bridge.tools import BridgeServices
from backend.auth.middleware import get_current_user

router = APIRouter(prefix="/api/agent-bridge", tags=["Agent Bridge"])

MAX_KEYS_PER_USER = 5
STREAM_POLL_SECONDS = 3.0
STREAM_MAX_SECONDS = 10 * 60


async def get_bridge_services() -> BridgeServices:
    """Dependency (overridden in tests)."""
    from backend.agent_bridge.mcp_app import default_services

    return await default_services()


def _uid(user: dict) -> str:
    return str(user["id"])


def _jsonable(row: Optional[dict]) -> Optional[dict]:
    if row is None:
        return None
    return json.loads(json.dumps(row, default=str))


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


class CreateKeyRequest(BaseModel):
    name: str = Field("Grok Bot", min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_SCOPES))
    expires_in_days: Optional[int] = Field(90, ge=1, le=365)


@router.post("/keys", status_code=201)
async def create_key(body: CreateKeyRequest, user: dict = Depends(get_current_user),
                     svc: BridgeServices = Depends(get_bridge_services)):
    try:
        scopes = validate_scopes(body.scopes)
    except InvalidScopeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    active = [k for k in await svc.repo.list_keys(_uid(user)) if not k.get("revoked_at")]
    if len(active) >= MAX_KEYS_PER_USER:
        raise HTTPException(status_code=409, detail="Too many active agent keys; revoke one first")
    expires = (datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
               if body.expires_in_days else None)
    row, full_key = await svc.repo.create_key(_uid(user), body.name, scopes, expires)
    return {"key": _jsonable(row), "api_key": full_key,
            "warning": "Copy this key now. GraphRecall stores only its hash."}


@router.get("/keys")
async def list_keys(user: dict = Depends(get_current_user),
                    svc: BridgeServices = Depends(get_bridge_services)):
    return {"keys": [_jsonable(k) for k in await svc.repo.list_keys(_uid(user))]}


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: str, user: dict = Depends(get_current_user),
                     svc: BridgeServices = Depends(get_bridge_services)):
    if not await svc.repo.revoke_key(_uid(user), key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    return {"revoked": True}


# ---------------------------------------------------------------------------
# Agent-curated feed items (approval)
# ---------------------------------------------------------------------------


@router.get("/feed-items")
async def list_feed_items(
    status: Optional[Literal["pending", "approved", "rejected", "expired"]] = "pending",
    target_date: Optional[date] = None,
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    svc: BridgeServices = Depends(get_bridge_services),
):
    rows = await svc.repo.list_feed_items(_uid(user), status=status, target_date=target_date,
                                          limit=limit)
    return {"items": [_jsonable(r) for r in rows]}


async def _set_status(item_id: str, status: str, user: dict, svc: BridgeServices):
    row = await svc.repo.set_feed_item_status(_uid(user), item_id, status)
    if row is None:
        raise HTTPException(status_code=404, detail="Feed item not found")
    return {"item": _jsonable(row)}


@router.post("/feed-items/{item_id}/approve")
async def approve_feed_item(item_id: str, user: dict = Depends(get_current_user),
                            svc: BridgeServices = Depends(get_bridge_services)):
    # TODO(agent-bridge): optional "auto-approve items from this key" user setting.
    return await _set_status(item_id, "approved", user, svc)


@router.post("/feed-items/{item_id}/reject")
async def reject_feed_item(item_id: str, user: dict = Depends(get_current_user),
                           svc: BridgeServices = Depends(get_bridge_services)):
    # TODO(agent-bridge): feed rejections back to the agent (e.g. a get_feedback tool)
    # so curation improves.
    return await _set_status(item_id, "rejected", user, svc)


# ---------------------------------------------------------------------------
# "Ask my agent" queue
# ---------------------------------------------------------------------------


class AskAgentRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    context: dict = Field(default_factory=dict,
                          description="Small, user-visible context (e.g. concept ids, topic)")


def _request_view(r: dict) -> dict:
    keep = ("id", "status", "question", "conversation_id", "created_at", "claimed_at",
            "answered_at", "answer_text", "answer_json", "error", "expires_at")
    return _jsonable({k: r.get(k) for k in keep})


@router.post("/requests", status_code=202)
async def ask_agent(body: AskAgentRequest, user: dict = Depends(get_current_user),
                    svc: BridgeServices = Depends(get_bridge_services)):
    """Hand a question to the user's external agent. Asynchronous: answers usually take
    minutes (the agent polls on a routine or is woken by the webhook)."""
    if len(json.dumps(body.context)) > 8000:
        raise HTTPException(status_code=413, detail="context too large")
    # TODO(agent-bridge): per-user rate limit on enqueue (e.g. 30/day).
    row = await svc.repo.enqueue_request(_uid(user), body.question, body.context,
                                         body.conversation_id)
    await svc.notifier.notify(_uid(user), "agent_request.created", {"request_id": row["id"]})
    return {"request": _request_view(row),
            "eta_note": "Your agent answers asynchronously, usually within minutes."}


@router.get("/requests")
async def list_requests(status: Optional[str] = None, limit: int = Query(20, ge=1, le=100),
                        user: dict = Depends(get_current_user),
                        svc: BridgeServices = Depends(get_bridge_services)):
    statuses = [s.strip() for s in status.split(",")] if status else None
    rows = await svc.repo.list_requests(_uid(user), statuses=statuses, limit=limit)
    return {"requests": [_request_view(r) for r in rows]}


@router.get("/requests/{request_id}")
async def get_request(request_id: str, user: dict = Depends(get_current_user),
                      svc: BridgeServices = Depends(get_bridge_services)):
    row = await svc.repo.get_request(_uid(user), request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return {"request": _request_view(row)}


@router.post("/requests/{request_id}/cancel")
async def cancel_request(request_id: str, user: dict = Depends(get_current_user),
                         svc: BridgeServices = Depends(get_bridge_services)):
    row = await svc.repo.cancel_request(_uid(user), request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found or already finished")
    return {"request": _request_view(row)}


@router.get("/requests/{request_id}/stream")
async def stream_request(request_id: str, user: dict = Depends(get_current_user),
                         svc: BridgeServices = Depends(get_bridge_services)):
    """SSE: emits ``status`` events on change and closes on a terminal state."""
    uid = _uid(user)
    if await svc.repo.get_request(uid, request_id) is None:
        raise HTTPException(status_code=404, detail="Request not found")

    async def gen():
        last = None
        waited = 0.0
        while waited <= STREAM_MAX_SECONDS:
            row = await svc.repo.get_request(uid, request_id)
            if row is None:
                break
            if row["status"] != last:
                last = row["status"]
                yield f"event: status\ndata: {json.dumps(_request_view(row))}\n\n"
            if row["status"] in REQUEST_TERMINAL:
                break
            # TODO(agent-bridge): replace polling with Postgres LISTEN/NOTIFY.
            await asyncio.sleep(STREAM_POLL_SECONDS)
            waited += STREAM_POLL_SECONDS
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
