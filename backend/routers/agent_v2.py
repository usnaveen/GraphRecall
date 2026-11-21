"""Additive FastAPI router for Always-On Agent v2 jobs, insights, and run telemetry."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.agent_v2.job_queue import PostgresInsightStore, PostgresJobQueue, PostgresRunLogger
from backend.agent_v2.protocols import (
    AgentInsight,
    AgentJob,
    AgentRunRecord,
    FeedInsightCard,
    HeartbeatDailyPayload,
    InsightStatus,
    InsightStore,
    JobQueue,
    JobStatus,
    NoteIngestedPayload,
    ReviewLapsedPayload,
    RunLogger,
)
from backend.auth.middleware import get_current_user
from backend.db.postgres_client import get_postgres_client

router = APIRouter(prefix="/api/v2/agent", tags=["Always-On Agent v2"])


async def get_job_queue() -> JobQueue:
    pg = await get_postgres_client()
    return PostgresJobQueue(pg)


async def get_insight_store() -> InsightStore:
    pg = await get_postgres_client()
    return PostgresInsightStore(pg)


async def get_run_logger() -> RunLogger:
    pg = await get_postgres_client()
    return PostgresRunLogger(pg)


class NoteIngestedTriggerRequest(BaseModel):
    note_id: str
    note_title: str = ""
    summary: str = ""
    concept_names: list[str] = Field(default_factory=list)


class ReviewLapsedTriggerRequest(BaseModel):
    concept_id: str
    concept_name: str
    lapse_count: int = Field(default=1, ge=1)
    note_id: Optional[str] = None


class BriefingTriggerRequest(BaseModel):
    window_days: int = Field(default=7, ge=1, le=90)
    max_items: int = Field(default=5, ge=1, le=20)


class JobListResponse(BaseModel):
    jobs: list[AgentJob]
    total: int


class InsightListResponse(BaseModel):
    insights: list[AgentInsight]
    total: int


class FeedInsightCardListResponse(BaseModel):
    cards: list[FeedInsightCard]
    total: int


class RunListResponse(BaseModel):
    runs: list[AgentRunRecord]
    total: int


@router.post("/triggers/note-ingested", response_model=AgentJob, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_note_ingested(
    body: NoteIngestedTriggerRequest,
    current_user: dict = Depends(get_current_user),
    queue: JobQueue = Depends(get_job_queue),
) -> AgentJob:
    """Enqueue a `note.ingested` background synthesis job for the authenticated user."""
    payload = NoteIngestedPayload(
        note_id=body.note_id,
        note_title=body.note_title,
        summary=body.summary,
        concept_names=body.concept_names,
    )
    return await queue.enqueue(
        str(current_user["id"]),
        "note.ingested",
        payload.model_dump(),
    )


@router.post("/triggers/review-lapsed", response_model=AgentJob, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_review_lapsed(
    body: ReviewLapsedTriggerRequest,
    current_user: dict = Depends(get_current_user),
    queue: JobQueue = Depends(get_job_queue),
) -> AgentJob:
    """Enqueue a `review.lapsed` background remediation job for the authenticated user."""
    payload = ReviewLapsedPayload(
        concept_id=body.concept_id,
        concept_name=body.concept_name,
        lapse_count=body.lapse_count,
        note_id=body.note_id,
    )
    return await queue.enqueue(
        str(current_user["id"]),
        "review.lapsed",
        payload.model_dump(),
    )


@router.post("/triggers/briefing", response_model=AgentJob, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_daily_briefing(
    body: BriefingTriggerRequest,
    current_user: dict = Depends(get_current_user),
    queue: JobQueue = Depends(get_job_queue),
) -> AgentJob:
    """Enqueue a `heartbeat.daily` proactive study briefing job for the authenticated user."""
    payload = HeartbeatDailyPayload(
        window_days=body.window_days,
        max_items=body.max_items,
    )
    return await queue.enqueue(
        str(current_user["id"]),
        "heartbeat.daily",
        payload.model_dump(),
    )


@router.get("/insights", response_model=InsightListResponse)
async def list_insights(
    status_filter: Optional[InsightStatus] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    insights: InsightStore = Depends(get_insight_store),
) -> InsightListResponse:
    """List proactive agent insights for the authenticated user."""
    items = await insights.list_for_user(
        str(current_user["id"]),
        status=status_filter,
        limit=limit,
    )
    return InsightListResponse(insights=items, total=len(items))


@router.get("/feed-cards", response_model=FeedInsightCardListResponse)
async def list_feed_insight_cards(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    insights: InsightStore = Depends(get_insight_store),
) -> FeedInsightCardListResponse:
    """Return active agent insights serialized as feed cards for iOS/Web Feed integration."""
    items = await insights.list_for_user(
        str(current_user["id"]),
        status="active",
        limit=limit,
    )
    cards = [
        FeedInsightCard(
            id=ins.id,
            insight_type=ins.insight_type,
            title=ins.title,
            body_md=ins.body_md,
            concept_ids=ins.concept_ids,
            source_quotes=ins.source_quotes,
            action_payload=ins.action_payload,
            created_at=ins.created_at,
        )
        for ins in items
    ]
    return FeedInsightCardListResponse(cards=cards, total=len(cards))


@router.post("/insights/{insight_id}/dismiss", response_model=AgentInsight)
async def dismiss_insight(
    insight_id: str,
    current_user: dict = Depends(get_current_user),
    insights: InsightStore = Depends(get_insight_store),
) -> AgentInsight:
    """Mark an insight card dismissed for the authenticated user."""
    updated = await insights.update_status(
        str(current_user["id"]),
        insight_id,
        "dismissed",
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight not found")
    return updated


@router.post("/insights/{insight_id}/act", response_model=AgentInsight)
async def act_on_insight(
    insight_id: str,
    current_user: dict = Depends(get_current_user),
    insights: InsightStore = Depends(get_insight_store),
) -> AgentInsight:
    """Mark an insight card acted upon for the authenticated user."""
    updated = await insights.update_status(
        str(current_user["id"]),
        insight_id,
        "acted",
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insight not found")
    return updated


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    status_filter: Optional[JobStatus] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    queue: JobQueue = Depends(get_job_queue),
) -> JobListResponse:
    """Inspect durable background jobs for the authenticated user."""
    items = await queue.list_jobs(
        str(current_user["id"]),
        status=status_filter,
        limit=limit,
    )
    return JobListResponse(jobs=items, total=len(items))


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    runs: RunLogger = Depends(get_run_logger),
) -> RunListResponse:
    """Inspect recent agent execution telemetry for the authenticated user."""
    items = await runs.list_for_user(str(current_user["id"]), limit=limit)
    return RunListResponse(runs=items, total=len(items))
