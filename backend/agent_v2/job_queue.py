"""Postgres (FOR UPDATE SKIP LOCKED) and in-memory implementations of Agent v2 stores."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import text

from backend.agent_v2.protocols import (
    AgentInsight,
    AgentJob,
    AgentRunRecord,
    InsightStatus,
    JobStatus,
    VerifiedQuote,
    utcnow,
)
from backend.db.postgres_client import PostgresClient


def _decode_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


def _row_to_job(row: dict[str, Any]) -> AgentJob:
    return AgentJob(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        job_type=str(row["job_type"]),
        payload=_decode_json(row.get("payload_json"), {}),
        status=row["status"],
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        run_after=row["run_after"],
        locked_at=row.get("locked_at"),
        locked_by=row.get("locked_by"),
        last_error=row.get("last_error"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_insight(row: dict[str, Any]) -> AgentInsight:
    raw_quotes = _decode_json(row.get("source_quotes"), [])
    quotes = [VerifiedQuote.model_validate(q) for q in raw_quotes]
    return AgentInsight(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        insight_type=row["insight_type"],
        title=str(row["title"]),
        body_md=str(row["body_md"]),
        concept_ids=[str(c) for c in _decode_json(row.get("concept_ids"), [])],
        source_quotes=quotes,
        action_payload=_decode_json(row.get("action_payload"), {}),
        status=row["status"],
        created_at=row["created_at"],
        expires_at=row.get("expires_at"),
    )


def _row_to_run(row: dict[str, Any]) -> AgentRunRecord:
    return AgentRunRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        trigger_type=str(row["trigger_type"]),
        job_id=str(row["job_id"]) if row.get("job_id") else None,
        thread_id=row.get("thread_id"),
        model=row.get("model"),
        tool_calls=_decode_json(row.get("tool_calls_json"), []),
        input_tokens=int(row.get("input_tokens") or 0),
        output_tokens=int(row.get("output_tokens") or 0),
        latency_ms=float(row.get("latency_ms") or 0.0),
        status=row["status"],
        error=row.get("error"),
        created_at=row["created_at"],
    )


class PostgresJobQueue:
    """Durable async Postgres queue using `FOR UPDATE SKIP LOCKED`."""

    def __init__(self, pg: PostgresClient):
        self._pg = pg

    async def enqueue(
        self,
        user_id: str,
        job_type: str,
        payload: dict[str, Any],
        *,
        max_attempts: int = 3,
        run_after: Optional[datetime] = None,
    ) -> AgentJob:
        run_ts = run_after or utcnow()
        rows = await self._pg.execute_query(
            """
            INSERT INTO agent_jobs (user_id, job_type, payload_json, max_attempts, run_after)
            VALUES (CAST(:user_id AS uuid), :job_type, CAST(:payload_json AS jsonb), :max_attempts, :run_after)
            RETURNING *
            """,
            {
                "user_id": user_id,
                "job_type": job_type,
                "payload_json": json.dumps(payload),
                "max_attempts": max_attempts,
                "run_after": run_ts,
            },
        )
        return _row_to_job(rows[0])

    async def claim_next(self, worker_id: str, *, lease_seconds: float = 300.0) -> Optional[AgentJob]:
        async with self._pg.session() as session:
            # First dead-letter expired running jobs that have exhausted attempts.
            await session.execute(
                text(
                    """
                    UPDATE agent_jobs
                    SET status = 'dead_letter',
                        locked_at = NULL,
                        locked_by = NULL,
                        last_error = COALESCE(last_error, 'worker lease expired after max attempts'),
                        updated_at = NOW()
                    WHERE status = 'running'
                      AND locked_at < NOW() - make_interval(secs => :lease_seconds)
                      AND attempts >= max_attempts
                    """
                ),
                {"lease_seconds": float(lease_seconds)},
            )
            result = await session.execute(
                text(
                    """
                    WITH next_job AS (
                        SELECT id
                        FROM agent_jobs
                        WHERE (status = 'pending' AND run_after <= NOW())
                           OR (
                               status = 'running'
                               AND locked_at < NOW() - make_interval(secs => :lease_seconds)
                               AND attempts < max_attempts
                           )
                        ORDER BY COALESCE(locked_at, run_after) ASC, created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE agent_jobs j
                    SET status = 'running',
                        attempts = j.attempts + 1,
                        locked_at = NOW(),
                        locked_by = :worker_id,
                        updated_at = NOW()
                    FROM next_job
                    WHERE j.id = next_job.id
                    RETURNING j.*
                    """
                ),
                {"worker_id": worker_id, "lease_seconds": float(lease_seconds)},
            )
            row = result.mappings().first()
            return _row_to_job(dict(row)) if row else None

    async def complete(self, job_id: str) -> None:
        await self._pg.execute_update(
            """
            UPDATE agent_jobs
            SET status = 'completed',
                locked_at = NULL,
                locked_by = NULL,
                updated_at = NOW()
            WHERE id = CAST(:job_id AS uuid)
            """,
            {"job_id": job_id},
        )

    async def fail(
        self,
        job_id: str,
        error: str,
        *,
        backoff_seconds: float = 15.0,
    ) -> AgentJob:
        rows = await self._pg.execute_query(
            """
            UPDATE agent_jobs
            SET status = CASE WHEN attempts >= max_attempts THEN 'dead_letter' ELSE 'pending' END,
                run_after = CASE
                    WHEN attempts >= max_attempts THEN run_after
                    ELSE NOW() + make_interval(secs => (:backoff_seconds * POWER(2, GREATEST(attempts - 1, 0))))
                END,
                locked_at = NULL,
                locked_by = NULL,
                last_error = :error,
                updated_at = NOW()
            WHERE id = CAST(:job_id AS uuid)
            RETURNING *
            """,
            {
                "job_id": job_id,
                "error": error[:4000],
                "backoff_seconds": float(backoff_seconds),
            },
        )
        if not rows:
            raise KeyError(f"Job not found: {job_id}")
        return _row_to_job(rows[0])

    async def list_jobs(
        self,
        user_id: str,
        *,
        status: Optional[JobStatus] = None,
        limit: int = 50,
    ) -> list[AgentJob]:
        if status is not None:
            rows = await self._pg.execute_query(
                """
                SELECT * FROM agent_jobs
                WHERE user_id = CAST(:user_id AS uuid) AND status = :status
                ORDER BY created_at DESC
                LIMIT :lim
                """,
                {"user_id": user_id, "status": status, "lim": limit},
            )
        else:
            rows = await self._pg.execute_query(
                """
                SELECT * FROM agent_jobs
                WHERE user_id = CAST(:user_id AS uuid)
                ORDER BY created_at DESC
                LIMIT :lim
                """,
                {"user_id": user_id, "lim": limit},
            )
        return [_row_to_job(r) for r in rows]


class PostgresInsightStore:
    """Async Postgres persistence for proactive agent insights."""

    def __init__(self, pg: PostgresClient):
        self._pg = pg

    async def save(self, insight: AgentInsight) -> AgentInsight:
        rows = await self._pg.execute_query(
            """
            INSERT INTO agent_insights (
                id, user_id, insight_type, title, body_md,
                concept_ids, source_quotes, action_payload, status, expires_at
            )
            VALUES (
                CAST(:id AS uuid), CAST(:user_id AS uuid), :insight_type, :title, :body_md,
                CAST(:concept_ids AS jsonb), CAST(:source_quotes AS jsonb),
                CAST(:action_payload AS jsonb), :status, :expires_at
            )
            RETURNING *
            """,
            {
                "id": insight.id,
                "user_id": insight.user_id,
                "insight_type": insight.insight_type,
                "title": insight.title,
                "body_md": insight.body_md,
                "concept_ids": json.dumps(insight.concept_ids),
                "source_quotes": json.dumps([q.model_dump() for q in insight.source_quotes]),
                "action_payload": json.dumps(insight.action_payload),
                "status": insight.status,
                "expires_at": insight.expires_at,
            },
        )
        return _row_to_insight(rows[0])

    async def list_for_user(
        self,
        user_id: str,
        *,
        status: Optional[InsightStatus] = None,
        limit: int = 50,
    ) -> list[AgentInsight]:
        if status is not None:
            rows = await self._pg.execute_query(
                """
                SELECT * FROM agent_insights
                WHERE user_id = CAST(:user_id AS uuid) AND status = :status
                ORDER BY created_at DESC
                LIMIT :lim
                """,
                {"user_id": user_id, "status": status, "lim": limit},
            )
        else:
            rows = await self._pg.execute_query(
                """
                SELECT * FROM agent_insights
                WHERE user_id = CAST(:user_id AS uuid)
                ORDER BY created_at DESC
                LIMIT :lim
                """,
                {"user_id": user_id, "lim": limit},
            )
        return [_row_to_insight(r) for r in rows]

    async def update_status(
        self,
        user_id: str,
        insight_id: str,
        status: InsightStatus,
    ) -> Optional[AgentInsight]:
        rows = await self._pg.execute_query(
            """
            UPDATE agent_insights
            SET status = :status
            WHERE id = CAST(:insight_id AS uuid)
              AND user_id = CAST(:user_id AS uuid)
            RETURNING *
            """,
            {"insight_id": insight_id, "user_id": user_id, "status": status},
        )
        return _row_to_insight(rows[0]) if rows else None


class PostgresRunLogger:
    """Async Postgres persistence for agent run telemetry."""

    def __init__(self, pg: PostgresClient):
        self._pg = pg

    async def record(self, run: AgentRunRecord) -> AgentRunRecord:
        rows = await self._pg.execute_query(
            """
            INSERT INTO agent_runs (
                id, user_id, trigger_type, job_id, thread_id, model,
                tool_calls_json, input_tokens, output_tokens, latency_ms, status, error
            )
            VALUES (
                CAST(:id AS uuid), CAST(:user_id AS uuid), :trigger_type,
                CAST(:job_id AS uuid), :thread_id, :model,
                CAST(:tool_calls_json AS jsonb), :input_tokens, :output_tokens,
                :latency_ms, :status, :error
            )
            RETURNING *
            """,
            {
                "id": run.id,
                "user_id": run.user_id,
                "trigger_type": run.trigger_type,
                "job_id": run.job_id,
                "thread_id": run.thread_id,
                "model": run.model,
                "tool_calls_json": json.dumps(run.tool_calls),
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "latency_ms": run.latency_ms,
                "status": run.status,
                "error": run.error,
            },
        )
        return _row_to_run(rows[0])

    async def list_for_user(self, user_id: str, *, limit: int = 50) -> list[AgentRunRecord]:
        rows = await self._pg.execute_query(
            """
            SELECT * FROM agent_runs
            WHERE user_id = CAST(:user_id AS uuid)
            ORDER BY created_at DESC
            LIMIT :lim
            """,
            {"user_id": user_id, "lim": limit},
        )
        return [_row_to_run(r) for r in rows]


class InMemoryJobQueue:
    """Deterministic in-memory JobQueue with atomic claim, lease recovery, and backoff."""

    def __init__(self, *, clock: Callable[[], datetime] = utcnow) -> None:
        self._jobs: dict[str, AgentJob] = {}
        self._order: list[str] = []
        self._lock = asyncio.Lock()
        self._clock = clock

    async def enqueue(
        self,
        user_id: str,
        job_type: str,
        payload: dict[str, Any],
        *,
        max_attempts: int = 3,
        run_after: Optional[datetime] = None,
    ) -> AgentJob:
        async with self._lock:
            now_ts = self._clock()
            job = AgentJob(
                id=str(uuid4()),
                user_id=user_id,
                job_type=job_type,
                payload=dict(payload),
                status="pending",
                attempts=0,
                max_attempts=max_attempts,
                run_after=run_after or now_ts,
                created_at=now_ts,
                updated_at=now_ts,
            )
            self._jobs[job.id] = job
            self._order.append(job.id)
            return job.model_copy(deep=True)

    async def claim_next(self, worker_id: str, *, lease_seconds: float = 300.0) -> Optional[AgentJob]:
        async with self._lock:
            now_ts = self._clock()
            lease_cutoff = now_ts - timedelta(seconds=float(lease_seconds))

            for jid in self._order:
                j = self._jobs[jid]
                if (
                    j.status == "running"
                    and j.locked_at is not None
                    and j.locked_at < lease_cutoff
                    and j.attempts >= j.max_attempts
                ):
                    self._jobs[jid] = j.model_copy(
                        update={
                            "status": "dead_letter",
                            "locked_at": None,
                            "locked_by": None,
                            "last_error": j.last_error or "worker lease expired after max attempts",
                            "updated_at": now_ts,
                        }
                    )

            eligible = [
                self._jobs[jid]
                for jid in self._order
                if (self._jobs[jid].status == "pending" and self._jobs[jid].run_after <= now_ts)
                or (
                    self._jobs[jid].status == "running"
                    and self._jobs[jid].locked_at is not None
                    and self._jobs[jid].locked_at < lease_cutoff
                    and self._jobs[jid].attempts < self._jobs[jid].max_attempts
                )
            ]
            if not eligible:
                return None
            eligible.sort(key=lambda j: (j.locked_at or j.run_after, j.created_at))
            job = eligible[0]
            updated = job.model_copy(
                update={
                    "status": "running",
                    "attempts": job.attempts + 1,
                    "locked_at": now_ts,
                    "locked_by": worker_id,
                    "updated_at": now_ts,
                }
            )
            self._jobs[job.id] = updated
            return updated.model_copy(deep=True)

    async def complete(self, job_id: str) -> None:
        async with self._lock:
            job = self._jobs[job_id]
            self._jobs[job_id] = job.model_copy(
                update={
                    "status": "completed",
                    "locked_at": None,
                    "locked_by": None,
                    "updated_at": self._clock(),
                }
            )

    async def fail(
        self,
        job_id: str,
        error: str,
        *,
        backoff_seconds: float = 15.0,
    ) -> AgentJob:
        async with self._lock:
            job = self._jobs[job_id]
            now_ts = self._clock()
            exhausted = job.attempts >= job.max_attempts
            delay = timedelta(seconds=backoff_seconds * (2 ** max(job.attempts - 1, 0)))
            updated = job.model_copy(
                update={
                    "status": "dead_letter" if exhausted else "pending",
                    "run_after": job.run_after if exhausted else now_ts + delay,
                    "locked_at": None,
                    "locked_by": None,
                    "last_error": error[:4000],
                    "updated_at": now_ts,
                }
            )
            self._jobs[job_id] = updated
            return updated.model_copy(deep=True)

    async def list_jobs(
        self,
        user_id: str,
        *,
        status: Optional[JobStatus] = None,
        limit: int = 50,
    ) -> list[AgentJob]:
        async with self._lock:
            items = [
                j.model_copy(deep=True)
                for j in self._jobs.values()
                if j.user_id == user_id and (status is None or j.status == status)
            ]
            items.sort(key=lambda j: j.created_at, reverse=True)
            return items[:limit]


class InMemoryInsightStore:
    """In-memory InsightStore for deterministic testing."""

    def __init__(self) -> None:
        self._items: dict[str, AgentInsight] = {}

    async def save(self, insight: AgentInsight) -> AgentInsight:
        stored = insight.model_copy(deep=True)
        self._items[stored.id] = stored
        return stored.model_copy(deep=True)

    async def list_for_user(
        self,
        user_id: str,
        *,
        status: Optional[InsightStatus] = None,
        limit: int = 50,
    ) -> list[AgentInsight]:
        items = [
            ins.model_copy(deep=True)
            for ins in self._items.values()
            if ins.user_id == user_id and (status is None or ins.status == status)
        ]
        items.sort(key=lambda ins: ins.created_at, reverse=True)
        return items[:limit]

    async def update_status(
        self,
        user_id: str,
        insight_id: str,
        status: InsightStatus,
    ) -> Optional[AgentInsight]:
        existing = self._items.get(insight_id)
        if existing is None or existing.user_id != user_id:
            return None
        updated = existing.model_copy(update={"status": status})
        self._items[insight_id] = updated
        return updated.model_copy(deep=True)


class InMemoryRunLogger:
    """In-memory RunLogger for deterministic testing."""

    def __init__(self) -> None:
        self._runs: list[AgentRunRecord] = []

    async def record(self, run: AgentRunRecord) -> AgentRunRecord:
        stored = run.model_copy(deep=True)
        self._runs.append(stored)
        return stored.model_copy(deep=True)

    async def list_for_user(self, user_id: str, *, limit: int = 50) -> list[AgentRunRecord]:
        items = [r.model_copy(deep=True) for r in self._runs if r.user_id == user_id]
        items.sort(key=lambda r: r.created_at, reverse=True)
        return items[:limit]
