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

from backend.agent_bridge import limits
from backend.agent_bridge.keys import (
    DEFAULT_SCOPES,
    InvalidScopeError,
    KeyConfigError,
    key_row_is_active,
    validate_scopes,
)
from backend.agent_bridge.repository import REQUEST_TERMINAL, InvalidTransitionError, is_uuid
from backend.agent_bridge.serialization import to_jsonable
from backend.agent_bridge.tools import BridgeServices
from backend.agent_bridge.webhook import dispatch_in_background
from backend.auth.middleware import get_current_user

router = APIRouter(prefix="/api/agent-bridge", tags=["Agent Bridge"])

MAX_KEYS_PER_USER = 5
STREAM_POLL_SECONDS = 3.0
STREAM_MAX_SECONDS = 10 * 60

# "Ask my agent" quota: limits.enqueue_per_hour() per user, enforced by svc.limiter
# (Postgres-backed in production, in-memory in dev/tests; see limits.py).


async def get_bridge_services() -> BridgeServices:
    """Dependency (overridden in tests)."""
    from backend.agent_bridge.mcp_app import default_services

    return await default_services()


def _uid(user: dict) -> str:
    return str(user["id"])


def _require_uuid(value: Optional[str], name: str) -> Optional[str]:
    """Malformed ids are a client error (400), not a database error (500)."""
    if value is None:
        return None
    if not is_uuid(value):
        raise HTTPException(status_code=400, detail=f"{name} must be a UUID")
    return str(value)


def _jsonable(row: Optional[dict]) -> Optional[dict]:
    """ISO 8601 timestamps with 'T' and offset (iOS-decodable), UUIDs as strings."""
    if row is None:
        return None
    return to_jsonable(row)


async def _audit(svc: BridgeServices, user: dict, action: str, **kw) -> None:
    try:
        await svc.repo.audit(_uid(user), action, actor="user", **kw)
    except Exception:  # auditing never breaks the request
        pass


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
    # Revoked and expired keys do not count toward the limit.
    active = [k for k in await svc.repo.list_keys(_uid(user)) if key_row_is_active(k)]
    if len(active) >= MAX_KEYS_PER_USER:
        raise HTTPException(status_code=409, detail="Too many active agent keys; revoke one first")
    expires = (datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
               if body.expires_in_days else None)
    try:
        row, full_key = await svc.repo.create_key(_uid(user), body.name, scopes, expires)
    except KeyConfigError:
        raise HTTPException(status_code=503, detail="Agent keys are not configured on this server")
    await _audit(svc, user, "key_created", key_id=row["id"], target_id=row["id"],
                 details={"scopes": scopes, "expires_in_days": body.expires_in_days})
    return {"key": _jsonable(row), "api_key": full_key,
            "warning": "Copy this key now. GraphRecall stores only its hash."}


@router.get("/keys")
async def list_keys(user: dict = Depends(get_current_user),
                    svc: BridgeServices = Depends(get_bridge_services)):
    return {"keys": [_jsonable(k) for k in await svc.repo.list_keys(_uid(user))]}


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: str, user: dict = Depends(get_current_user),
                     svc: BridgeServices = Depends(get_bridge_services)):
    _require_uuid(key_id, "key_id")
    if not await svc.repo.revoke_key(_uid(user), key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    await _audit(svc, user, "key_revoked", key_id=key_id, target_id=key_id)
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
    _require_uuid(item_id, "item_id")
    try:
        row = await svc.repo.set_feed_item_status(_uid(user), item_id, status)
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if row is None:
        raise HTTPException(status_code=404, detail="Feed item not found")
    await _audit(svc, user, f"feed_item_{status}", key_id=row.get("key_id"), target_id=item_id)
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
    conversation_id = _require_uuid(body.conversation_id, "conversation_id")
    if len(json.dumps(body.context)) > 8000:
        raise HTTPException(status_code=413, detail="context too large")
    if conversation_id and not await svc.repo.conversation_owned(_uid(user), conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not await svc.limiter.hit(f"enqueue:user:{_uid(user)}", limits.enqueue_per_hour(), 3600):
        raise HTTPException(status_code=429, detail="Too many questions for your agent; try later",
                            headers={"Retry-After": "600"})
    row = await svc.repo.enqueue_request(_uid(user), body.question, body.context,
                                         conversation_id)
    # Never block the response on the webhook (it retries with backoff in the background).
    dispatch_in_background(svc.notifier, _uid(user), "agent_request.created",
                           {"request_id": row["id"]})
    await _audit(svc, user, "question_enqueued", target_id=row["id"])
    return {"request": _request_view(row),
            "eta_note": "Your agent answers asynchronously, usually within minutes."}


@router.get("/requests")
async def list_requests(status: Optional[str] = None, limit: int = Query(20, ge=1, le=100),
                        user: dict = Depends(get_current_user),
                        svc: BridgeServices = Depends(get_bridge_services)):
    statuses = [s.strip() for s in status.split(",")] if status else None
    allowed = {"queued", "claimed"} | REQUEST_TERMINAL
    if statuses and not set(statuses) <= allowed:
        raise HTTPException(status_code=400, detail=f"status must be in {sorted(allowed)}")
    rows = await svc.repo.list_requests(_uid(user), statuses=statuses, limit=limit)
    return {"requests": [_request_view(r) for r in rows]}


@router.get("/requests/{request_id}")
async def get_request(request_id: str, user: dict = Depends(get_current_user),
                      svc: BridgeServices = Depends(get_bridge_services)):
    _require_uuid(request_id, "request_id")
    row = await svc.repo.get_request(_uid(user), request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return {"request": _request_view(row)}


@router.post("/requests/{request_id}/cancel")
async def cancel_request(request_id: str, user: dict = Depends(get_current_user),
                         svc: BridgeServices = Depends(get_bridge_services)):
    _require_uuid(request_id, "request_id")
    row = await svc.repo.cancel_request(_uid(user), request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Request not found or already finished")
    return {"request": _request_view(row)}


@router.get("/requests/{request_id}/stream")
async def stream_request(request_id: str, user: dict = Depends(get_current_user),
                         svc: BridgeServices = Depends(get_bridge_services)):
    """SSE: emits ``status`` events on change and closes on a terminal state
    (answered / failed / cancelled / expired - reads sweep stale rows first)."""
    _require_uuid(request_id, "request_id")
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
        yield ("event: end\ndata: "
               + json.dumps({"status": last, "terminal": last in REQUEST_TERMINAL}) + "\n\n")

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/audit")
async def list_audit(limit: int = Query(100, ge=1, le=500), user: dict = Depends(get_current_user),
                     svc: BridgeServices = Depends(get_bridge_services)):
    """What the user's agents (and the user, for keys/approvals) did through the bridge."""
    return {"events": [_jsonable(r) for r in await svc.repo.list_audit(_uid(user), limit)]}
