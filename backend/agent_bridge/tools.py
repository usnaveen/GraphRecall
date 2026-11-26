"""Agent-bridge MCP tool handlers (transport-agnostic, unit-testable).

Each tool declares the scope it needs. The principal (bound to one user) comes from
the authenticated agent key - tools never accept a ``user_id`` argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Awaitable, Callable, Literal, Optional
from uuid import UUID

import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from backend.agent_bridge.dedupe import compute_dedupe_key, is_safe_http_url
from backend.agent_bridge.keys import (
    SCOPE_BRIDGE_ANSWER,
    SCOPE_READ_KNOWLEDGE,
    SCOPE_WRITE_FEED,
    AgentPrincipal,
    ScopeError,
    require_scope,
)
from backend.agent_bridge.knowledge import KnowledgeService
from backend.agent_bridge import limits
from backend.agent_bridge.limits import InMemoryRateLimiter, RateLimiter
from backend.agent_bridge.repository import (
    DEFAULT_MAX_ATTEMPTS,
    BridgeRepository,
    LimitExceededError,
)
from backend.agent_bridge.serialization import iso, to_jsonable
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
    limiter: RateLimiter = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.limiter is None:
            self.limiter = InMemoryRateLimiter()


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


def _check_url(v: Optional[str]) -> Optional[str]:
    if v is not None and not is_safe_http_url(v):
        raise ValueError("URL must be an absolute http(s) URL")
    return v.strip() if v else v


UuidStr = Annotated[UUID, Field(description="UUID")]


class _Args(BaseModel):
    model_config = {"extra": "forbid"}


class ProfileArgs(_Args):
    limit: int = Field(10, ge=1, le=50, description="Max weak/strong concepts to return")


class AssessArgs(_Args):
    names: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(..., min_length=1, max_length=100)
    track_unknown: bool = Field(False, description="Queue unexposed names so the app asks the user (needs write:feed)")


class BlueprintArgs(_Args):
    pass


class FrontierArgs(_Args):
    query: str = Field(..., min_length=1, max_length=400)
    concept_names: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=30)
    max_hops: int = Field(2, ge=1, le=3)


class RecordExposureArgs(_Args):
    concept: str = Field(..., min_length=1, max_length=160)
    context: str = Field(..., min_length=1, max_length=600)
    source: str = Field("agent_session", min_length=1, max_length=80)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    source_url: Optional[str] = Field(None, max_length=2048)
    create_if_missing: bool = False

    @field_validator("source_url")
    @classmethod
    def _url(cls, v: Optional[str]) -> Optional[str]:
        return _check_url(v or None)


class LaterArgs(_Args):
    text: str = Field(..., min_length=1, max_length=1000)
    url: Optional[str] = Field(None, max_length=2000)
    when: Optional[str] = Field(None, max_length=60, description="e.g. 'tomorrow', 'this weekend', 'in 3 days'")


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
        return _check_url(v or None)

    @model_validator(mode="after")
    def _kind_body(self) -> "ProposedItem":
        if self.item_kind == "flashcard" and self.flashcard is None:
            raise ValueError("flashcard items need 'flashcard' {front, back}")
        return self


class ProposeArgs(_Args):
    items: list[ProposedItem] = Field(..., min_length=1, max_length=MAX_ITEMS_PER_CALL)


class DigestArgs(_Args):
    digest_date: Optional[date] = None
    title: str = Field(..., min_length=1, max_length=500)
    summary: str = Field("", max_length=4000)
    item_ids: list[UuidStr] = Field(default_factory=list, max_length=50)
    focus_concept_ids: list[str] = Field(default_factory=list, max_length=20)


class ListQuestionsArgs(_Args):
    limit: int = Field(10, ge=1, le=50)


class ClaimArgs(_Args):
    request_id: Optional[UuidStr] = Field(None, description="Claim a specific question; else the oldest")
    lease_seconds: int = Field(15 * 60, ge=MIN_LEASE, le=MAX_LEASE)


class Citation(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(..., max_length=500)
    url: Optional[str] = Field(None, max_length=2048)

    @field_validator("url")
    @classmethod
    def _url(cls, v: Optional[str]) -> Optional[str]:
        return _check_url(v or None)


class SubmitArgs(_Args):
    request_id: UuidStr
    claim_token: UuidStr
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


_iso = iso


async def _profile(p: AgentPrincipal, s: BridgeServices, a: ProfileArgs) -> dict:
    return await s.knowledge.get_knowledge_profile(p.user_id, limit=a.limit)


async def _assess(p: AgentPrincipal, s: BridgeServices, a: AssessArgs) -> dict:
    from backend.services import knowledge_map as km

    if a.track_unknown:
        require_scope(p, SCOPE_WRITE_FEED)
    results = await km.assess(p.user_id, a.names, pg=s.knowledge.pg, neo4j=s.knowledge.neo4j, max_names=100)
    if a.track_unknown:
        # Cap what an agent can queue: at most 10 per call, and nothing while 50 agent questions wait.
        waiting = await s.knowledge.pg.execute_query(
            "SELECT count(*) AS n FROM user_skills WHERE user_id = CAST(:u AS uuid) AND self_rating IS NULL "
            "AND 'agent' = ANY(sources)", {"u": p.user_id})
        room = max(0, 50 - int((waiting or [{"n": 0}])[0]["n"]))
        for r in [r for r in results if r.status == "unexposed" and r.self_rating is None][:min(10, room)]:
            await km.upsert_skill(s.knowledge.pg, p.user_id, r.name, source="agent")
    keep = ("name", "status", "mastery", "confidence", "basis", "concept_name", "domain", "evidence")
    return {"results": [{k: v for k, v in r.as_dict().items() if k in keep} for r in results],
            "legend": {"strong": "tested well, or backed by coursework/projects/self-rating",
                       "shaky": "struggled when tested, or self-rated low",
                       "seen": "studied or claimed, never tested",
                       "unexposed": "no evidence the user has met this"}}


async def _frontier(p: AgentPrincipal, s: BridgeServices, a: FrontierArgs) -> dict:
    return await s.knowledge.get_knowledge_frontier(
        p.user_id,
        a.query,
        concept_names=a.concept_names,
        max_hops=a.max_hops,
    )


async def _record_exposure(p: AgentPrincipal, s: BridgeServices, a: RecordExposureArgs) -> dict:
    return await s.knowledge.record_exposure(
        p.user_id,
        a.concept,
        a.context,
        source=a.source,
        confidence=a.confidence,
        source_url=a.source_url,
        create_if_missing=a.create_if_missing,
    )


async def _blueprint(p: AgentPrincipal, s: BridgeServices, a: BlueprintArgs) -> dict:
    from backend.services import knowledge_map as km

    pg = s.knowledge.pg
    profile = await pg.execute_query(
        "SELECT headline, education_status, institution, program, graduation_year, goals FROM user_profile "
        "WHERE user_id = CAST(:u AS uuid)", {"u": p.user_id})
    courses = await pg.execute_query(
        "SELECT code, name, term, grade, topics FROM user_courses WHERE user_id = CAST(:u AS uuid) "
        "ORDER BY created_at DESC", {"u": p.user_id})
    projects = await pg.execute_query(
        "SELECT name, summary, skills, started, ended FROM user_projects WHERE user_id = CAST(:u AS uuid) "
        "ORDER BY created_at DESC",
        {"u": p.user_id})
    knowledge = await km.summary(p.user_id, pg=pg, neo4j=s.knowledge.neo4j)
    knowledge.pop("items", None)
    return to_jsonable({"profile": dict(profile[0]) if profile else {}, "courses": [dict(c) for c in courses or []],
                        "projects": [dict(x) for x in projects or []], "knowledge": knowledge})


async def _later(p: AgentPrincipal, s: BridgeServices, a: LaterArgs) -> dict:
    from backend.services.later import parse_later

    url = (a.url or "").strip() or None
    if url and not is_safe_http_url(url):
        raise ToolError("invalid_arguments", "url must be a public http(s) URL")
    parsed = parse_later(a.text, when=a.when)
    if not parsed.text and not url:
        raise ToolError("invalid_arguments", "Nothing to save: give some text beyond the time phrase, or a url")
    if a.when and not parsed.phrase:
        raise ToolError("invalid_arguments", f"Unrecognised when {a.when!r}: use e.g. tomorrow, tonight, "
                                             "this weekend, next week, friday, in 3 days, or YYYY-MM-DD")
    rows = await s.knowledge.pg.execute_query(
        "INSERT INTO later_items (user_id, text, url, source, when_phrase, show_at) VALUES "
        "(CAST(:u AS uuid), :t, :url, 'agent', :ph, :at) RETURNING id::text AS id, show_at",
        {"u": p.user_id, "t": parsed.text or url, "url": url, "ph": parsed.phrase, "at": parsed.show_at})
    return {"ok": True, "id": rows[0]["id"], "show_at": iso(rows[0]["show_at"]), "when_phrase": parsed.phrase}


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
    # Whole batch is validated by ProposeArgs before we get here; nothing is written
    # unless every item is valid, and the write itself is one transaction.
    if not await s.limiter.hit(f"propose:key:{p.key_id}", limits.proposals_per_key_per_day(),
                               86400, cost=len(a.items)):
        raise ToolError("rate_limited",
                        f"This key may propose at most {limits.proposals_per_key_per_day()} "
                        "items per day")
    all_cids = sorted({c for it in a.items for c in it.concept_ids})
    owned = await s.knowledge.owned_concept_ids(p.user_id, all_cids) if all_cids else set()
    rows_in = []
    dropped_per_item = []
    for it in a.items:
        dropped_per_item.append([c for c in it.concept_ids if c not in owned])
        rows_in.append({
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
    try:
        written = await s.repo.insert_feed_items(p.user_id, rows_in,
                                                 max_pending_today=limits.max_pending_per_day())
    except LimitExceededError as e:
        raise ToolError("rate_limited", f"{e}. Ask the user to review pending items first.")
    results = [
        {**_feed_view(row), "created": created, "deduplicated": not created,
         "dropped_concept_ids": dropped}
        for (row, created), dropped in zip(written, dropped_per_item)
    ]
    return {
        "items": results,
        "note": "Items stay 'pending' until the user approves them in GraphRecall.",
    }


async def _digest(p: AgentPrincipal, s: BridgeServices, a: DigestArgs) -> dict:
    item_ids = [str(i) for i in a.item_ids]
    owned = await s.repo.owned_feed_item_ids(p.user_id, item_ids)
    missing = [i for i in item_ids if i not in owned]
    if missing:
        raise ToolError("not_found", f"Unknown feed item ids: {missing}")
    owned_c = await s.knowledge.owned_concept_ids(p.user_id, a.focus_concept_ids) \
        if a.focus_concept_ids else set()
    row = await s.repo.upsert_digest(p.user_id, {
        "key_id": p.key_id,
        "digest_date": a.digest_date or _today(),
        "title": a.title,
        "summary": a.summary,
        "item_ids": item_ids,
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
    # list_requests sweeps first, so expired / attempt-exhausted questions are already
    # terminal and drop out of this status filter.
    rows = await s.repo.list_requests(p.user_id, statuses=["queued", "claimed"], limit=a.limit)
    now = datetime.now(timezone.utc)

    def live(r: dict) -> bool:
        exp = r.get("expires_at")
        if exp is not None and exp <= now:
            return False
        lease = r.get("lease_expires_at")
        lapsed = r["status"] == "claimed" and lease is not None and lease < now
        return not (lapsed and r.get("attempts", 0) >= DEFAULT_MAX_ATTEMPTS)

    def claimable(r: dict) -> bool:
        lease = r.get("lease_expires_at")
        return r.get("attempts", 0) < DEFAULT_MAX_ATTEMPTS and (
            r["status"] == "queued" or (lease is not None and lease < now))

    return {"questions": [{**_question_view(r), "claimable": claimable(r)}
                          for r in rows if live(r)]}


async def _claim(p: AgentPrincipal, s: BridgeServices, a: ClaimArgs) -> dict:
    row = await s.repo.claim_request(
        p.user_id, p.key_id,
        request_id=str(a.request_id) if a.request_id else None,
        lease_seconds=a.lease_seconds)
    if row is None:
        return {"claimed": False, "question": None}
    return {"claimed": True, "question": _question_view(row, include_token=True)}


async def _submit(p: AgentPrincipal, s: BridgeServices, a: SubmitArgs) -> dict:
    if not a.answer_markdown and not a.error:
        raise ToolError("invalid_arguments", "Provide answer_markdown or error")
    row = await s.repo.complete_request(
        p.user_id, str(a.request_id), str(a.claim_token),
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
    ToolSpec("assess_concepts", SCOPE_READ_KNOWLEDGE,
             "Before teaching, check what the user already knows. Pass concept or skill names (e.g. a "
             "paper's prerequisites). Each returns strong / shaky / seen (studied, untested) / unexposed, "
             "with mastery 0-1, confidence and the evidence kinds behind it. Skip what they know, slow down "
             "on shaky items, introduce unexposed ones from scratch.", AssessArgs, _assess),
    ToolSpec("get_capability_blueprint", SCOPE_READ_KNOWLEDGE,
             "The user's education, courses with grades and topics, projects with skills, and a knowledge "
             "summary by status and domain. Never includes resume text or note bodies.", BlueprintArgs, _blueprint),
    ToolSpec("get_knowledge_frontier", SCOPE_READ_KNOWLEDGE,
             "Given a question/topic and optional concept names, returns anchors (strong), frontier (shaky), "
             "gaps (unexposed), misconceptions, provenance, resume claims at risk, and a cacheable profile prefix hash.",
             FrontierArgs, _frontier),
    ToolSpec("record_exposure", SCOPE_WRITE_FEED,
             "Record that the user encountered or discussed a concept in an external agent session, updating "
             "knowledge_evidence and user_skills provenance without overwriting test mastery.",
             RecordExposureArgs, _record_exposure),
    ToolSpec("suggest_for_later", SCOPE_WRITE_FEED,
             "Queue an article, paper or topic in the user's 'Later' list so it returns in their feed at a "
             "chosen time ('tomorrow', 'this weekend', 'in 3 days'). Labelled as from their agent.",
             LaterArgs, _later),
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


def audit_counts(name: str, data: Any) -> dict:
    """Metadata for the audit log: list sizes and a few flags, never content."""
    out: dict[str, Any] = {}
    if not isinstance(data, dict):
        return out
    for k, v in data.items():
        if isinstance(v, list):
            out[f"{k}_count"] = len(v)
    if name == "propose_feed_items":
        items = data.get("items") or []
        out["created"] = sum(1 for i in items if i.get("created"))
        out["deduplicated"] = sum(1 for i in items if i.get("deduplicated"))
    if name == "claim_question":
        out["claimed"] = bool(data.get("claimed"))
    if name == "submit_answer":
        out["status"] = data.get("status")
    if name == "get_knowledge_profile":
        out["total_concepts"] = data.get("total_concepts")
    if name == "get_knowledge_frontier":
        out["anchors_count"] = len(data.get("anchors") or [])
        out["frontier_count"] = len(data.get("frontier") or [])
        out["gaps_count"] = len(data.get("gaps") or [])
    if name == "record_exposure":
        out["matched_existing"] = bool(data.get("matched_existing"))
    return out


def _audit_target(name: str, data: Any) -> Optional[str]:
    if name == "submit_answer":
        return data.get("request_id")
    if name == "claim_question" and data.get("question"):
        return data["question"].get("id")
    if name == "schedule_daily_digest":
        return (data.get("digest") or {}).get("id")
    return None


async def call_tool(name: str, principal: AgentPrincipal, services: BridgeServices,
                    arguments: Optional[dict] = None) -> dict:
    """Validate, authorize and run a tool. Always returns a JSON-serializable dict.
    Successful calls are recorded in the audit log (names/ids/counts only)."""
    spec = TOOLS.get(name)
    if spec is None:
        return {"ok": False, "error": {"code": "unknown_tool", "message": name}}
    try:
        require_scope(principal, spec.scope)
        args = spec.model.model_validate(arguments or {})
        data = to_jsonable(await spec.handler(principal, services, args))
        try:
            await services.repo.audit(
                principal.user_id, "answer_submitted" if name == "submit_answer" else "tool_call",
                actor="agent", key_id=principal.key_id, tool=name,
                target_id=_audit_target(name, data), details=audit_counts(name, data))
        except Exception as e:  # auditing must never break the tool
            logger.warning("agent_bridge: audit failed", tool=name, error=str(e))
        return {"ok": True, "data": data}
    except ScopeError as e:
        return {"ok": False, "error": {"code": "forbidden", "message": str(e)}}
    except ValidationError as e:
        return {"ok": False, "error": {"code": "invalid_arguments",
                                        "message": e.errors(include_url=False, include_input=False,
                                                             include_context=False)}}
    except ToolError as e:
        return {"ok": False, "error": {"code": e.code, "message": e.message}}
    except Exception as e:  # pragma: no cover - defensive
        logger.error("agent_bridge: tool failed", tool=name, error=str(e))
        return {"ok": False, "error": {"code": "internal", "message": "Tool failed"}}
