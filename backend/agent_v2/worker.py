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
    HeartbeatDailyPayload,
    InsightStore,
    JobQueue,
    LLMGateway,
    MemoryFacade,
    NoteIngestedPayload,
    ReviewLapsedPayload,
    RunLogger,
    VerifiedQuote,
)
from backend.agent_v2.provenance import validate_proposed_bridges, verify_quote_in_text
from backend.db.postgres_client import close_postgres_client, get_postgres_client

logger = structlog.get_logger()

JobHandler = Callable[[AgentJob], Awaitable[None]]


async def _record_skipped_run(
    runs: RunLogger,
    job: AgentJob,
    started: float,
    tool_call: dict,
) -> None:
    await runs.record(
        AgentRunRecord(
            user_id=job.user_id,
            trigger_type=job.job_type,
            job_id=job.id,
            tool_calls=[tool_call],
            latency_ms=(time.perf_counter() - started) * 1000.0,
            status="completed",
        )
    )


async def _record_failed_run(
    runs: RunLogger,
    job: AgentJob,
    started: float,
    tool_name: str,
    exc: Exception,
) -> None:
    await runs.record(
        AgentRunRecord(
            user_id=job.user_id,
            trigger_type=job.job_type,
            job_id=job.id,
            tool_calls=[{"tool": tool_name, "error": str(exc)}],
            latency_ms=(time.perf_counter() - started) * 1000.0,
            status="failed",
            error=str(exc),
        )
    )


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
        await _record_skipped_run(
            runs,
            job,
            started,
            {
                "tool": "memory.fetch_note_and_related_chunks",
                "note_chunks": len(note_chunks),
                "candidate_chunks": len(candidate_chunks),
                "skipped_reason": "insufficient_cross_note_context",
            },
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
        await _record_failed_run(runs, job, started, "llm.propose_bridges", exc)
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


async def handle_review_lapsed(
    job: AgentJob,
    *,
    memory: MemoryFacade,
    llm: LLMGateway,
    insights: InsightStore,
    runs: RunLogger,
) -> Optional[AgentInsight]:
    """Process a `review.lapsed` event into a provenance-grounded remedial insight card."""
    started = time.perf_counter()
    payload = ReviewLapsedPayload.model_validate(job.payload)

    context = await memory.fetch_concept_review_context(
        job.user_id,
        payload.concept_id,
        payload.concept_name,
        note_id=payload.note_id,
    )
    if not context.chunks:
        await _record_skipped_run(
            runs,
            job,
            started,
            {
                "tool": "memory.fetch_concept_review_context",
                "chunks": 0,
                "skipped_reason": "no_supporting_chunks",
            },
        )
        return None

    try:
        diagnosis, llm_meta = await llm.diagnose_review_lapse(
            context=context,
            lapse_count=payload.lapse_count,
        )
    except Exception as exc:
        await _record_failed_run(runs, job, started, "llm.diagnose_review_lapse", exc)
        raise

    chunks_by_id = {c.chunk_id: c for c in context.chunks}
    cited_chunk = chunks_by_id.get(diagnosis.source_chunk_id)
    rejection_reason: Optional[str] = None
    if cited_chunk is None:
        rejection_reason = "missing_source_chunk"
    elif not verify_quote_in_text(diagnosis.source_quote, cited_chunk.content):
        rejection_reason = "unverified_source_quote"

    if rejection_reason is not None or cited_chunk is None:
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
                        "tool": "provenance.verify_quote_in_text",
                        "accepted": 0,
                        "rejected": 1,
                        "rejection_reason": rejection_reason,
                    }
                ],
                latency_ms=(time.perf_counter() - started) * 1000.0,
                status="completed",
            )
        )
        return None

    verified_quote = VerifiedQuote(
        chunk_id=cited_chunk.chunk_id,
        note_id=cited_chunk.note_id,
        note_title=cited_chunk.note_title,
        quote=diagnosis.source_quote.strip(),
    )
    body_md = (
        f"{diagnosis.explanation}\n\n"
        f"**Quick Recall Prompt:** {diagnosis.study_prompt}\n\n"
        f'> "{verified_quote.quote}" — *{verified_quote.note_title}*'
    )
    concept_ids = [payload.concept_id]
    if diagnosis.missing_prerequisite and diagnosis.missing_prerequisite not in concept_ids:
        concept_ids.append(diagnosis.missing_prerequisite)

    saved = await insights.save(
        AgentInsight(
            user_id=job.user_id,
            insight_type="remedial",
            title=diagnosis.title,
            body_md=body_md,
            concept_ids=concept_ids,
            source_quotes=[verified_quote],
            action_payload={
                "concept_id": payload.concept_id,
                "concept_name": payload.concept_name,
                "lapse_count": payload.lapse_count,
                "missing_prerequisite": diagnosis.missing_prerequisite,
                "prerequisite_graph_available": context.has_prerequisite_edges,
                "study_prompt": diagnosis.study_prompt,
            },
        )
    )
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
                    "tool": "provenance.verify_quote_in_text",
                    "accepted": 1,
                    "rejected": 0,
                    "prerequisite_graph_available": context.has_prerequisite_edges,
                }
            ],
            latency_ms=(time.perf_counter() - started) * 1000.0,
            status="completed",
        )
    )
    return saved


async def handle_heartbeat_daily(
    job: AgentJob,
    *,
    memory: MemoryFacade,
    llm: LLMGateway,
    insights: InsightStore,
    runs: RunLogger,
) -> Optional[AgentInsight]:
    """Process a `heartbeat.daily` event into a provenance-grounded daily study briefing."""
    started = time.perf_counter()
    payload = HeartbeatDailyPayload.model_validate(job.payload)

    digest = await memory.fetch_learning_digest(
        job.user_id,
        window_days=payload.window_days,
        limit=max(payload.max_items, 8),
    )
    if not digest.sample_chunks or (
        digest.recent_notes_count == 0 and not digest.due_concepts and not digest.lapsed_concepts
    ):
        await _record_skipped_run(
            runs,
            job,
            started,
            {
                "tool": "memory.fetch_learning_digest",
                "sample_chunks": len(digest.sample_chunks),
                "skipped_reason": "empty_learning_digest",
            },
        )
        return None

    try:
        draft, llm_meta = await llm.compose_daily_briefing(
            digest=digest,
            window_days=payload.window_days,
        )
    except Exception as exc:
        await _record_failed_run(runs, job, started, "llm.compose_daily_briefing", exc)
        raise

    chunks_by_id = {c.chunk_id: c for c in digest.sample_chunks}
    cited_chunk = chunks_by_id.get(draft.cited_chunk_id)
    rejection_reason: Optional[str] = None
    if cited_chunk is None:
        rejection_reason = "missing_cited_chunk"
    elif not verify_quote_in_text(draft.cited_quote, cited_chunk.content):
        rejection_reason = "unverified_cited_quote"

    if rejection_reason is not None or cited_chunk is None:
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
                        "tool": "provenance.verify_quote_in_text",
                        "accepted": 0,
                        "rejected": 1,
                        "rejection_reason": rejection_reason,
                    }
                ],
                latency_ms=(time.perf_counter() - started) * 1000.0,
                status="completed",
            )
        )
        return None

    verified_quote = VerifiedQuote(
        chunk_id=cited_chunk.chunk_id,
        note_id=cited_chunk.note_id,
        note_title=cited_chunk.note_title,
        quote=draft.cited_quote.strip(),
    )
    body_md = f'{draft.summary_md}\n\n> "{verified_quote.quote}" — *{verified_quote.note_title}*'
    saved = await insights.save(
        AgentInsight(
            user_id=job.user_id,
            insight_type="briefing",
            title=draft.title,
            body_md=body_md,
            concept_ids=draft.priority_concepts or digest.due_concepts[:3],
            source_quotes=[verified_quote],
            action_payload={
                "window_days": payload.window_days,
                "priority_concepts": draft.priority_concepts,
                "recent_notes_count": digest.recent_notes_count,
            },
        )
    )
    await runs.record(
        AgentRunRecord(
            user_id=job.user_id,
            trigger_type=job.job_type,
            job_id=job.id,
            model=llm_meta.get("model"),
            input_tokens=int(llm_meta.get("input_tokens", 0)),
            output_tokens=int(llm_meta.get("output_tokens", 0)),
            tool_calls=[{"tool": "provenance.verify_quote_in_text", "accepted": 1, "rejected": 0}],
            latency_ms=(time.perf_counter() - started) * 1000.0,
            status="completed",
        )
    )
    return saved


class AgentWorker:
    """Async daemon polling a JobQueue and dispatching registered vertical-slice handlers."""

    def __init__(
        self,
        job_queue: JobQueue,
        *,
        worker_id: Optional[str] = None,
        poll_interval_s: float = 2.0,
        backoff_base_s: float = 15.0,
        lease_seconds: float = 300.0,
    ) -> None:
        self._queue = job_queue
        self._worker_id = worker_id or f"worker-{os.getpid()}"
        self._poll_interval_s = poll_interval_s
        self._backoff_base_s = backoff_base_s
        self._lease_seconds = lease_seconds
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    async def process_one(self) -> bool:
        """Claim and execute a single due job. Returns True if a job was processed."""
        job = await self._queue.claim_next(self._worker_id, lease_seconds=self._lease_seconds)
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

    async def _on_review_lapsed(job: AgentJob) -> None:
        await handle_review_lapsed(
            job,
            memory=memory,
            llm=llm,
            insights=insights,
            runs=runs,
        )

    async def _on_heartbeat_daily(job: AgentJob) -> None:
        await handle_heartbeat_daily(
            job,
            memory=memory,
            llm=llm,
            insights=insights,
            runs=runs,
        )

    worker.register("note.ingested", _on_note_ingested)
    worker.register("review.lapsed", _on_review_lapsed)
    worker.register("heartbeat.daily", _on_heartbeat_daily)
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
