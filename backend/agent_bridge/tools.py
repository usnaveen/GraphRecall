"""Agent-bridge MCP tool handlers (transport-agnostic, unit-testable).

Each tool declares the scope it needs. The principal (bound to one user) comes from
the authenticated agent key - tools never accept a ``user_id`` argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Literal, Optional

import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.agent_bridge.dedupe import compute_dedupe_key, normalize_url
from backend.agent_bridge.keys import (
    SCOPE_BRIDGE_ANSWER,
    SCOPE_READ_KNOWLEDGE,
    SCOPE_WRITE_FEED,
    AgentPrincipal,
    ScopeError,
    require_scope,
)
from backend.agent_bridge.knowledge import KnowledgeService
from backend.agent_bridge.repository import BridgeRepository
from backend.agent_bridge.webhook import Notifier, NullNotifier

logger = structlog.get_logger()

MAX_ITEMS_PER_CALL = 20
MIN_LEASE, MAX_LEASE = 60, 60 * 60


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class BridgeServices:
    repo: BridgeRepository
    knowledge: KnowledgeService
    notifier: Notifier = NullNotifier()


Handler = Callable[[AgentPrincipal, BridgeServices, dict], Awaitable[Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    scope: str
    description: str
    model: type[BaseModel]
    handler: Handler

    @property
    def input_schema(self) -> dict:
        return self.model.model_json_schema()


# ---------------------------------------------------------------------------
# Argument models
# ---------------------------------------------------------------------------


class _Args(BaseModel):
    model_config = {"extra": "forbid"}


class ProfileArgs(_Args):
    limit: int = Field(10, ge=1, le=50, description="Max weak/strong concepts to return")


class SearchArgs(_Args):
    query: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(10, ge=1, le=50)


class NeighborhoodArgs(_Args):
    concept_id: str = Field(..., min_length=1, max_length=255)
    limit: int = Field(15, ge=1, le=25)


class DueArgs(_Args):
    limit: int = Field(20, ge=1, le=100)


class ActivityArgs(_Args):
    days: int = Field(7, ge=1, le=90)
    limit: int = Field(20, ge=1, le=100)


class FlashcardBody(BaseModel):
    front: str = Field(..., max_length=1000)
    back: str = Field(..., max_length=2000)


class ProposedItem(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(..., min_length=1, max_length=500)
    summary: str = Field(
        ..., min_length=1, max_length=2000,
        description="Curated summary in your own words. Never paste raw email bodies.",
    )
    reason: str = Field(..., min_length=1, max_length=1000,
                        description="Why this matters for the user today (shown in the app)")
    source_url: Optional[str] = Field(None, max_length=2048)
    source_kind: Literal["email", "substack", "web", "exam", "calendar", "other"] = "web"
    item_kind: Literal["article", "flashcard", "mcq", "exam_prep", "note"] = "article"
    concept_ids: list[str] = Field(default_factory=list, max_length=20)
    target_date: Optional[date] = Field(None, description="Day it should appear (default today)")
    idempotency_key: Optional[str] = Field(None, min_length=1, max_length=128)
    flashcard: Optional[FlashcardBody] = None

    @field_validator("source_url")
    @classmethod
    def _url(cls, v: Optional[str]) -> Optional[str]:
        if v and normalize_url(v) is None:
            raise ValueError("source_url must be an http(s) URL")
        return v


class ProposeArgs(_Args):
    items: list[ProposedItem] = Field(..., min_length=1, max_length=MAX_ITEMS_PER_CALL)


class DigestArgs(_Args):
    digest_date: Optional[date] = None
    title: str = Field(..., min_length=1, max_length=500)
    summary: str = Field("", max_length=4000)
    item_ids: list[str] = Field(default_factory=list, max_length=50)
    focus_concept_ids: list[str] = Field(default_factory=list, max_length=20)


class ListQuestionsArgs(_Args):
    limit: int = Field(10, ge=1, le=50)


class ClaimArgs(_Args):
    request_id: Optional[str] = Field(None, description="Claim a specific question; else the oldest")
    lease_seconds: int = Field(15 * 60, ge=MIN_LEASE, le=MAX_LEASE)


class Citation(BaseModel):
    title: str = Field(..., max_length=500)
    url: Optional[str] = Field(None, max_length=2048)


class SubmitArgs(_Args):
    request_id: str
    claim_token: str
    answer_markdown: Optional[str] = Field(None, max_length=20000)
    citations: list[Citation] = Field(default_factory=list, max_length=20)
    error: Optional[str] = Field(None, max_length=2000,
                                 description="Set instead of an answer if you could not answer")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _today() -> date:
    # TODO(agent-bridge): use the user's timezone (users.settings_json) instead of UTC.
    return datetime.now(timezone.utc).date()


def _iso(v: Any) -> Any:
    return v.isoformat() if hasattr(v, "isoformat") else v


async def _profile(p: AgentPrincipal, s: BridgeServices, a: ProfileArgs) -> dict:
    return await s.knowledge.get_knowledge_profile(p.user_id, limit=a.limit)


async def _search(p: AgentPrincipal, s: BridgeServices, a: SearchArgs) -> dict:
    return {"concepts": await s.knowledge.search_concepts(p.user_id, a.query, limit=a.limit)}


async def _neighborhood(p: AgentPrincipal, s: BridgeServices, a: NeighborhoodArgs) -> dict:
    res = await s.knowledge.get_concept_neighborhood(p.user_id, a.concept_id, limit=a.limit)
    if res is None:
        # Same error for "missing" and "belongs to someone else" - no existence oracle.
        raise ToolError("not_found", "Concept not found")
    return res


async def _due(p: AgentPrincipal, s: BridgeServices, a: DueArgs) -> dict:
    return {"due": await s.knowledge.list_due_reviews(p.user_id, limit=a.limit)}


async def _activity(p: AgentPrincipal, s: BridgeServices, a: ActivityArgs) -> dict:
    return await s.knowledge.get_recent_activity(p.user_id, days=a.days, limit=a.limit)


def _feed_view(r: dict) -> dict:
    return {
        "id": r["id"], "status": r["status"], "title": r["title"],
        "target_date": _iso(r["target_date"]), "source_url": r.get("source_url"),
        "item_kind": r.get("item_kind"),
    }


async def _propose(p: AgentPrincipal, s: BridgeServices, a: ProposeArgs) -> dict:
    all_cids = sorted({c for it in a.items for c in it.concept_ids})
    owned = await s.knowledge.owned_concept_ids(p.user_id, all_cids) if all_cids else set()
    results = []
    for it in a.items:
        dropped = [c for c in it.concept_ids if c not in owned]
        if it.item_kind == "flashcard" and it.flashcard is None:
            raise ToolError("invalid_arguments", f"'{it.title}': flashcard items need 'flashcard'")
        row, created = await s.repo.insert_feed_item(p.user_id, {
            "key_id": p.key_id,
            "item_kind": it.item_kind,
            "title": it.title.strip(),
            "summary": it.summary.strip(),
            "body_json": {"flashcard": it.flashcard.model_dump()} if it.flashcard else {},
            "source_url": it.source_url,
            "source_kind": it.source_kind,
            "reason": it.reason.strip(),
            "concept_ids": [c for c in it.concept_ids if c in owned],
            "target_date": it.target_date or _today(),
            "dedupe_key": compute_dedupe_key(it.source_url, it.title, it.summary),
            "idempotency_key": it.idempotency_key,
        })
        results.append({**_feed_view(row), "created": created,
                        "deduplicated": not created, "dropped_concept_ids": dropped})
    return {
        "items": results,
        "note": "Items stay 'pending' until the user approves them in GraphRecall.",
    }


async def _digest(p: AgentPrincipal, s: BridgeServices, a: DigestArgs) -> dict:
    owned = await s.repo.owned_feed_item_ids(p.user_id, a.item_ids)
    missing = [i for i in a.item_ids if i not in owned]
    if missing:
        raise ToolError("not_found", f"Unknown feed item ids: {missing}")
    owned_c = await s.knowledge.owned_concept_ids(p.user_id, a.focus_concept_ids) \
        if a.focus_concept_ids else set()
    row = await s.repo.upsert_digest(p.user_id, {
        "key_id": p.key_id,
        "digest_date": a.digest_date or _today(),
        "title": a.title,
        "summary": a.summary,
        "item_ids": a.item_ids,
        "focus_concept_ids": [c for c in a.focus_concept_ids if c in owned_c],
    })
    # TODO(agent-bridge): surface the digest as a header card in the feed (iOS + web).
    return {"digest": {"id": row["id"], "digest_date": _iso(row["digest_date"]),
                       "title": row["title"], "item_ids": row["item_ids"]}}


def _question_view(r: dict, *, include_token: bool = False) -> dict:
    out = {
        "id": r["id"], "status": r["status"], "question": r["question"],
        "context": r.get("context_json") or {}, "created_at": _iso(r.get("created_at")),
        "attempts": r.get("attempts", 0), "lease_expires_at": _iso(r.get("lease_expires_at")),
    }
    if include_token:
        out["claim_token"] = r.get("claim_token")
    return out


async def _list_questions(p: AgentPrincipal, s: BridgeServices, a: ListQuestionsArgs) -> dict:
    rows = await s.repo.list_requests(p.user_id, statuses=["queued", "claimed"], limit=a.limit)
    now = datetime.now(timezone.utc)

    def claimable(r: dict) -> bool:
        lease = r.get("lease_expires_at")
        return r["status"] == "queued" or (lease is not None and lease < now)

    return {"questions": [{**_question_view(r), "claimable": claimable(r)} for r in rows]}


async def _claim(p: AgentPrincipal, s: BridgeServices, a: ClaimArgs) -> dict:
    row = await s.repo.claim_request(p.user_id, p.key_id, request_id=a.request_id,
                                     lease_seconds=a.lease_seconds)
    if row is None:
        return {"claimed": False, "question": None}
    return {"claimed": True, "question": _question_view(row, include_token=True)}


async def _submit(p: AgentPrincipal, s: BridgeServices, a: SubmitArgs) -> dict:
    if not a.answer_markdown and not a.error:
        raise ToolError("invalid_arguments", "Provide answer_markdown or error")
    row = await s.repo.complete_request(
        p.user_id, a.request_id, a.claim_token,
        answer_text=a.answer_markdown,
        answer_json={"citations": [c.model_dump() for c in a.citations]},
        error=a.error,
    )
    if row is None:
        raise ToolError("conflict", "Question not claimed by this token, lease expired, or not found")
    # TODO(agent-bridge): push notification to iOS/web that the answer is ready
    # (clients currently poll GET /api/agent-bridge/requests/{id} or its SSE stream).
    return {"ok": True, "request_id": row["id"], "status": row["status"]}


# ---------------------------------------------------------------------------
# Registry + dispatch
# ---------------------------------------------------------------------------

TOOLS: dict[str, ToolSpec] = {t.name: t for t in [
    ToolSpec("get_knowledge_profile", SCOPE_READ_KNOWLEDGE,
             "Summary of the user's knowledge: domains with average mastery, weakest and "
             "strongest concepts, and how many reviews are due.", ProfileArgs, _profile),
    ToolSpec("search_concepts", SCOPE_READ_KNOWLEDGE,
             "Find the user's concepts by name/definition substring, with mastery (0-1).",
             SearchArgs, _search),
    ToolSpec("get_concept_neighborhood", SCOPE_READ_KNOWLEDGE,
             "A concept plus its directly linked concepts (1 hop, max 25).",
             NeighborhoodArgs, _neighborhood),
    ToolSpec("list_due_reviews", SCOPE_READ_KNOWLEDGE,
             "Concepts due for spaced-repetition review now, highest priority first.",
             DueArgs, _due),
    ToolSpec("get_recent_activity", SCOPE_READ_KNOWLEDGE,
             "Recent reviews and newly added notes (titles/links only).", ActivityArgs, _activity),
    ToolSpec("propose_feed_items", SCOPE_WRITE_FEED,
             "Propose curated cards for the user's feed. Idempotent: pass idempotency_key; "
             "duplicates (same normalized URL or content on the same target_date) return the "
             "existing item. Items are 'pending' until the user approves them.",
             ProposeArgs, _propose),
    ToolSpec("schedule_daily_digest", SCOPE_WRITE_FEED,
             "Create/replace the curated digest for a day, referencing proposed feed items.",
             DigestArgs, _digest),
    ToolSpec("list_pending_questions", SCOPE_BRIDGE_ANSWER,
             "Questions the user's in-app assistant handed off to you.",
             ListQuestionsArgs, _list_questions),
    ToolSpec("claim_question", SCOPE_BRIDGE_ANSWER,
             "Atomically claim one question with a lease. Returns claim_token for submit_answer.",
             ClaimArgs, _claim),
    ToolSpec("submit_answer", SCOPE_BRIDGE_ANSWER,
             "Answer a claimed question (markdown + citations), or report an error.",
             SubmitArgs, _submit),
]}


async def call_tool(name: str, principal: AgentPrincipal, services: BridgeServices,
                    arguments: Optional[dict] = None) -> dict:
    """Validate, authorize and run a tool. Always returns a JSON-serializable dict."""
    spec = TOOLS.get(name)
    if spec is None:
        return {"ok": False, "error": {"code": "unknown_tool", "message": name}}
    try:
        require_scope(principal, spec.scope)
        args = spec.model.model_validate(arguments or {})
        data = await spec.handler(principal, services, args)
        return {"ok": True, "data": data}
    except ScopeError as e:
        return {"ok": False, "error": {"code": "forbidden", "message": str(e)}}
    except ValidationError as e:
        return {"ok": False, "error": {"code": "invalid_arguments",
                                        "message": e.errors(include_url=False, include_input=False)}}
    except ToolError as e:
        return {"ok": False, "error": {"code": e.code, "message": e.message}}
    except Exception as e:  # pragma: no cover - defensive
        logger.error("agent_bridge: tool failed", tool=name, error=str(e))
        return {"ok": False, "error": {"code": "internal", "message": "Tool failed"}}
