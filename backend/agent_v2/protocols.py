"""Typed models and black-box Protocol interfaces for GraphRecall Always-On Agent v2."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field

JobStatus = Literal["pending", "running", "completed", "dead_letter"]
InsightType = Literal["connection", "conflict", "remedial", "briefing"]
InsightStatus = Literal["active", "dismissed", "acted"]
BridgeRelationship = Literal["RELATED_TO", "PREREQUISITE_OF", "CONTRASTS_WITH", "SUPPORTS"]


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class NoteChunk(BaseModel):
    """Source chunk retrieved for provenance-grounded reasoning."""

    chunk_id: str
    note_id: str
    note_title: str = "Untitled"
    content: str


class VerifiedQuote(BaseModel):
    """Verbatim source quote verified against its source chunk."""

    chunk_id: str
    note_id: str
    note_title: str
    quote: str


class ProposedBridge(BaseModel):
    """LLM-proposed cross-note bridge or conflict requiring quote verification."""

    source_concept: str
    target_concept: str
    relationship_type: BridgeRelationship = "RELATED_TO"
    title: str
    explanation: str
    source_chunk_id: str
    source_quote: str
    target_chunk_id: str
    target_quote: str


class BridgeProposalBatch(BaseModel):
    """Structured batch output returned by an LLMGateway."""

    bridges: list[ProposedBridge] = Field(default_factory=list)


class VerifiedBridge(BaseModel):
    """A proposed bridge that passed 'no quote, no edge' provenance validation."""

    proposal: ProposedBridge
    verified_quotes: list[VerifiedQuote]


class RejectedBridge(BaseModel):
    """A proposed bridge rejected by provenance validation."""

    proposal: ProposedBridge
    reason: str


class ProvenanceReport(BaseModel):
    """Outcome of validating a batch of proposed bridges against source chunks."""

    accepted: list[VerifiedBridge] = Field(default_factory=list)
    rejected: list[RejectedBridge] = Field(default_factory=list)


class NoteIngestedPayload(BaseModel):
    """Typed payload for `note.ingested` background jobs."""

    note_id: str
    note_title: str = ""
    summary: str = ""
    concept_names: list[str] = Field(default_factory=list)


class ReviewLapsedPayload(BaseModel):
    """Typed payload for `review.lapsed` background jobs."""

    concept_id: str
    concept_name: str
    lapse_count: int = 1
    note_id: Optional[str] = None


class HeartbeatDailyPayload(BaseModel):
    """Typed payload for `heartbeat.daily` briefing jobs."""

    window_days: int = 7
    max_items: int = 5


class ConceptReviewContext(BaseModel):
    """Retrieved study context for diagnosing a lapsed concept review."""

    concept_id: str
    concept_name: str
    prerequisites: list[str] = Field(default_factory=list)
    has_prerequisite_edges: bool = False
    chunks: list[NoteChunk] = Field(default_factory=list)


class UserLearningDigest(BaseModel):
    """User-scoped learning summary for daily briefing composition."""

    recent_notes_count: int = 0
    due_concepts: list[str] = Field(default_factory=list)
    lapsed_concepts: list[str] = Field(default_factory=list)
    sample_chunks: list[NoteChunk] = Field(default_factory=list)


class RemedialDiagnosis(BaseModel):
    """Structured remedial explanation requiring an exact verbatim quote."""

    title: str
    explanation: str
    missing_prerequisite: Optional[str] = None
    source_chunk_id: str
    source_quote: str
    study_prompt: str


class DailyBriefingDraft(BaseModel):
    """Structured daily learning briefing requiring an exact verbatim quote."""

    title: str
    summary_md: str
    priority_concepts: list[str] = Field(default_factory=list)
    cited_chunk_id: str
    cited_quote: str


class FeedInsightCard(BaseModel):
    """Feed-ready serializer view of an active AgentInsight."""

    id: str
    card_type: Literal["agent_insight"] = "agent_insight"
    insight_type: InsightType
    title: str
    body_md: str
    concept_ids: list[str]
    source_quotes: list[VerifiedQuote]
    action_payload: dict[str, Any]
    created_at: datetime


class AgentJob(BaseModel):
    """Durable background job record."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    job_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus = "pending"
    attempts: int = 0
    max_attempts: int = 3
    run_after: datetime = Field(default_factory=utcnow)
    locked_at: Optional[datetime] = None
    locked_by: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AgentInsight(BaseModel):
    """Proactive insight card produced by the always-on worker."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    insight_type: InsightType
    title: str
    body_md: str
    concept_ids: list[str] = Field(default_factory=list)
    source_quotes: list[VerifiedQuote] = Field(default_factory=list)
    action_payload: dict[str, Any] = Field(default_factory=dict)
    status: InsightStatus = "active"
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: Optional[datetime] = None


class AgentRunRecord(BaseModel):
    """Observability telemetry row for one agent execution."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    trigger_type: str
    job_id: Optional[str] = None
    thread_id: Optional[str] = None
    model: Optional[str] = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    status: Literal["completed", "failed"] = "completed"
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


@runtime_checkable
class JobQueue(Protocol):
    """Black-box durable job queue interface."""

    async def enqueue(
        self,
        user_id: str,
        job_type: str,
        payload: dict[str, Any],
        *,
        max_attempts: int = 3,
        run_after: Optional[datetime] = None,
    ) -> AgentJob: ...

    async def claim_next(self, worker_id: str, *, lease_seconds: float = 300.0) -> Optional[AgentJob]: ...

    async def complete(self, job_id: str) -> None: ...

    async def fail(
        self,
        job_id: str,
        error: str,
        *,
        backoff_seconds: float = 15.0,
    ) -> AgentJob: ...

    async def list_jobs(
        self,
        user_id: str,
        *,
        status: Optional[JobStatus] = None,
        limit: int = 50,
    ) -> list[AgentJob]: ...


@runtime_checkable
class InsightStore(Protocol):
    """Black-box storage interface for proactive agent insights."""

    async def save(self, insight: AgentInsight) -> AgentInsight: ...

    async def list_for_user(
        self,
        user_id: str,
        *,
        status: Optional[InsightStatus] = None,
        limit: int = 50,
    ) -> list[AgentInsight]: ...

    async def update_status(
        self,
        user_id: str,
        insight_id: str,
        status: InsightStatus,
    ) -> Optional[AgentInsight]: ...


@runtime_checkable
class RunLogger(Protocol):
    """Black-box telemetry logger for agent executions."""

    async def record(self, run: AgentRunRecord) -> AgentRunRecord: ...

    async def list_for_user(self, user_id: str, *, limit: int = 50) -> list[AgentRunRecord]: ...


@runtime_checkable
class MemoryFacade(Protocol):
    """Black-box retrieval interface over the user's notes and knowledge graph."""

    async def fetch_note_and_related_chunks(
        self,
        user_id: str,
        note_id: str,
        concept_names: list[str],
        *,
        limit: int = 12,
    ) -> list[NoteChunk]: ...

    async def fetch_concept_review_context(
        self,
        user_id: str,
        concept_id: str,
        concept_name: str,
        *,
        note_id: Optional[str] = None,
        limit: int = 6,
    ) -> ConceptReviewContext: ...

    async def fetch_learning_digest(
        self,
        user_id: str,
        *,
        window_days: int = 7,
        limit: int = 8,
    ) -> UserLearningDigest: ...


@runtime_checkable
class LLMGateway(Protocol):
    """Black-box gateway for structured LLM synthesis calls (never swallows errors)."""

    async def propose_bridges(
        self,
        *,
        note_title: str,
        note_chunks: list[NoteChunk],
        candidate_chunks: list[NoteChunk],
        concept_names: list[str],
    ) -> tuple[BridgeProposalBatch, dict[str, Any]]: ...

    async def diagnose_review_lapse(
        self,
        *,
        context: ConceptReviewContext,
        lapse_count: int,
    ) -> tuple[RemedialDiagnosis, dict[str, Any]]: ...

    async def compose_daily_briefing(
        self,
        *,
        digest: UserLearningDigest,
        window_days: int,
    ) -> tuple[DailyBriefingDraft, dict[str, Any]]: ...
