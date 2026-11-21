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
    InsightStatus,
    InsightStore,
    JobQueue,
    JobStatus,
    NoteIngestedPayload,
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


class JobListResponse(BaseModel):
    jobs: list[AgentJob]
    total: int


class InsightListResponse(BaseModel):
    insights: list[AgentInsight]
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
