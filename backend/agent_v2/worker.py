"""Always-On Agent worker daemon and vertical-slice job handlers."""

from __future__ import annotations

import asyncio
import os
import signal
import time
from collections.abc import Awaitable, Callable
from typing import Optional

import structlog

from backend.agent_v2.adapters import GeminiLLMGateway, PostgresMemoryFacade
from backend.agent_v2.job_queue import PostgresInsightStore, PostgresJobQueue, PostgresRunLogger
from backend.agent_v2.protocols import (
    AgentInsight,
    AgentJob,
    AgentRunRecord,
    InsightStore,
    JobQueue,
    LLMGateway,
    MemoryFacade,
    NoteIngestedPayload,
    RunLogger,
)
from backend.agent_v2.provenance import validate_proposed_bridges
from backend.db.postgres_client import close_postgres_client, get_postgres_client

logger = structlog.get_logger()

JobHandler = Callable[[AgentJob], Awaitable[None]]


async def handle_note_ingested(
    job: AgentJob,
    *,
    memory: MemoryFacade,
    llm: LLMGateway,
    insights: InsightStore,
    runs: RunLogger,
) -> list[AgentInsight]:
    """Process a `note.ingested` event into provenance-verified proactive insight cards."""
    started = time.perf_counter()
    payload = NoteIngestedPayload.model_validate(job.payload)

    chunks = await memory.fetch_note_and_related_chunks(
        job.user_id,
        payload.note_id,
        payload.concept_names,
    )
    chunks_by_id = {c.chunk_id: c for c in chunks}
    note_chunks = [c for c in chunks if c.note_id == payload.note_id]
    candidate_chunks = [c for c in chunks if c.note_id != payload.note_id]

    if not note_chunks or not candidate_chunks:
        latency_ms = (time.perf_counter() - started) * 1000.0
        await runs.record(
            AgentRunRecord(
                user_id=job.user_id,
                trigger_type=job.job_type,
                job_id=job.id,
                tool_calls=[
                    {
                        "tool": "memory.fetch_note_and_related_chunks",
                        "note_chunks": len(note_chunks),
                        "candidate_chunks": len(candidate_chunks),
                        "skipped_reason": "insufficient_cross_note_context",
                    }
                ],
                latency_ms=latency_ms,
                status="completed",
            )
        )
        return []

    try:
        batch, llm_meta = await llm.propose_bridges(
            note_title=payload.note_title or note_chunks[0].note_title,
            note_chunks=note_chunks,
            candidate_chunks=candidate_chunks,
            concept_names=payload.concept_names,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        await runs.record(
            AgentRunRecord(
                user_id=job.user_id,
                trigger_type=job.job_type,
                job_id=job.id,
                tool_calls=[{"tool": "llm.propose_bridges", "error": str(exc)}],
                latency_ms=latency_ms,
                status="failed",
                error=str(exc),
            )
        )
        raise

    report = validate_proposed_bridges(batch.bridges, chunks_by_id)
    saved_insights: list[AgentInsight] = []

    for verified in report.accepted:
        prop = verified.proposal
        insight_type = "conflict" if prop.relationship_type == "CONTRASTS_WITH" else "connection"
        quotes_md = "\n".join(
            f'> "{q.quote}" — *{q.note_title}*' for q in verified.verified_quotes
        )
        body_md = f"{prop.explanation}\n\n{quotes_md}"
        insight = AgentInsight(
            user_id=job.user_id,
            insight_type=insight_type,
            title=prop.title,
            body_md=body_md,
            concept_ids=[prop.source_concept, prop.target_concept],
            source_quotes=verified.verified_quotes,
            action_payload={
                "note_id": payload.note_id,
                "relationship_type": prop.relationship_type,
                "source_concept": prop.source_concept,
                "target_concept": prop.target_concept,
            },
        )
        saved_insights.append(await insights.save(insight))

    latency_ms = (time.perf_counter() - started) * 1000.0
    await runs.record(
        AgentRunRecord(
            user_id=job.user_id,
            trigger_type=job.job_type,
            job_id=job.id,
            model=llm_meta.get("model"),
            input_tokens=int(llm_meta.get("input_tokens", 0)),
            output_tokens=int(llm_meta.get("output_tokens", 0)),
            tool_calls=[
                {
                    "tool": "provenance.validate_proposed_bridges",
                    "proposed": len(batch.bridges),
                    "accepted": len(report.accepted),
                    "rejected": len(report.rejected),
                    "rejection_reasons": [r.reason for r in report.rejected],
                }
            ],
            latency_ms=latency_ms,
            status="completed",
        )
    )
    return saved_insights


class AgentWorker:
    """Async daemon polling a JobQueue and dispatching registered vertical-slice handlers."""

    def __init__(
        self,
        job_queue: JobQueue,
        *,
        worker_id: Optional[str] = None,
        poll_interval_s: float = 2.0,
        backoff_base_s: float = 15.0,
    ) -> None:
        self._queue = job_queue
        self._worker_id = worker_id or f"worker-{os.getpid()}"
        self._poll_interval_s = poll_interval_s
        self._backoff_base_s = backoff_base_s
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    async def process_one(self) -> bool:
        """Claim and execute a single due job. Returns True if a job was processed."""
        job = await self._queue.claim_next(self._worker_id)
        if job is None:
            return False

        handler = self._handlers.get(job.job_type)
        if handler is None:
            err = f"No handler registered for job_type={job.job_type!r}"
            logger.error("agent_worker.unknown_job_type", job_id=job.id, job_type=job.job_type)
            await self._queue.fail(job.id, err, backoff_seconds=self._backoff_base_s)
            return True

        try:
            await handler(job)
        except Exception as exc:
            logger.warning(
                "agent_worker.job_failed",
                job_id=job.id,
                job_type=job.job_type,
                attempt=job.attempts,
                error=str(exc),
            )
            await self._queue.fail(job.id, str(exc), backoff_seconds=self._backoff_base_s)
        else:
            await self._queue.complete(job.id)
            logger.info("agent_worker.job_completed", job_id=job.id, job_type=job.job_type)
        return True

    async def run_forever(self, stop_event: Optional[asyncio.Event] = None) -> None:
        """Poll for jobs until `stop_event` is set."""
        stopper = stop_event or asyncio.Event()
        logger.info("agent_worker.started", worker_id=self._worker_id)
        while not stopper.is_set():
            did_work = await self.process_one()
            if not did_work:
                try:
                    await asyncio.wait_for(stopper.wait(), timeout=self._poll_interval_s)
                except asyncio.TimeoutError:
                    continue
        logger.info("agent_worker.stopped", worker_id=self._worker_id)


async def build_default_worker() -> AgentWorker:
    """Construct the Postgres-backed AgentWorker with default handlers."""
    pg = await get_postgres_client()
    await pg.initialize_schema()

    queue = PostgresJobQueue(pg)
    insights = PostgresInsightStore(pg)
    runs = PostgresRunLogger(pg)
    memory = PostgresMemoryFacade(pg)
    llm = GeminiLLMGateway()

    worker = AgentWorker(queue)

    async def _on_note_ingested(job: AgentJob) -> None:
        await handle_note_ingested(
            job,
            memory=memory,
            llm=llm,
            insights=insights,
            runs=runs,
        )

    worker.register("note.ingested", _on_note_ingested)
    return worker


async def _run_main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    worker = await build_default_worker()
    try:
        await worker.run_forever(stop_event=stop_event)
    finally:
        await close_postgres_client()


def main() -> None:
    asyncio.run(_run_main())


if __name__ == "__main__":
    main()
