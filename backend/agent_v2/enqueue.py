"""Helper for best-effort durable job enqueueing onto `agent_jobs`."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

import structlog

from backend.agent_v2.job_queue import PostgresJobQueue
from backend.agent_v2.protocols import AgentJob, JobQueue, utcnow

logger = structlog.get_logger()


async def _has_recent_active_job(
    queue: JobQueue,
    user_id: str,
    job_type: str,
    dedupe_window_seconds: int,
) -> bool:
    if isinstance(queue, PostgresJobQueue):
        rows = await queue._pg.execute_query(  # noqa: SLF001 - intentional typed Postgres check
            """
            SELECT id
            FROM agent_jobs
            WHERE user_id = CAST(:user_id AS uuid)
              AND job_type = :job_type
              AND status IN ('pending', 'running')
              AND created_at >= NOW() - make_interval(secs => :window_seconds)
            LIMIT 1
            """,
            {
                "user_id": user_id,
                "job_type": job_type,
                "window_seconds": int(dedupe_window_seconds),
            },
        )
        return bool(rows)

    now = utcnow()
    existing = await queue.list_jobs(user_id, limit=50)
    for job in existing:
        if (
            job.job_type == job_type
            and job.status in ("pending", "running")
            and (now - job.created_at).total_seconds() <= dedupe_window_seconds
        ):
            return True
    return False


async def enqueue_durable_job(
    user_id: str,
    job_type: str,
    payload: dict[str, Any],
    *,
    max_attempts: int = 3,
    delay_seconds: float = 0.0,
    dedupe_window_seconds: Optional[int] = None,
    pg_client=None,
    job_queue: Optional[JobQueue] = None,
) -> Optional[AgentJob]:
    """Best-effort enqueue onto `agent_jobs`, with optional active-job deduplication."""
    try:
        if job_queue is not None:
            queue = job_queue
        elif pg_client is not None:
            queue = PostgresJobQueue(pg_client)
        else:
            from backend.routers import agent_v2 as agent_v2_router

            queue = await agent_v2_router.get_job_queue()

        if dedupe_window_seconds is not None and dedupe_window_seconds > 0:
            if await _has_recent_active_job(queue, user_id, job_type, dedupe_window_seconds):
                logger.info(
                    "durable_job.deduplicated",
                    user_id=user_id,
                    job_type=job_type,
                    window_seconds=dedupe_window_seconds,
                )
                return None

        run_after = utcnow() + timedelta(seconds=delay_seconds) if delay_seconds > 0 else None
        return await queue.enqueue(
            user_id,
            job_type,
            payload,
            max_attempts=max_attempts,
            run_after=run_after,
        )
    except Exception as exc:  # noqa: BLE001 - durable enqueue must never break API request
        logger.warning(
            "durable_job.enqueue_failed",
            user_id=user_id,
            job_type=job_type,
            error=str(exc),
        )
        return None
