"""100% offline unit & API tests for Always-On Agent v2 (no live Postgres, Neo4j, or Gemini)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.agent_v2.job_queue import (
    InMemoryInsightStore,
    InMemoryJobQueue,
    InMemoryRunLogger,
)
from backend.agent_v2.protocols import (
    BridgeProposalBatch,
    NoteChunk,
    ProposedBridge,
)
from backend.agent_v2.provenance import (
    validate_proposed_bridges,
    verify_quote_in_text,
)
from backend.agent_v2.worker import AgentWorker, handle_note_ingested
from backend.auth.middleware import get_current_user
from backend.main import app
from backend.routers import agent_v2 as agent_v2_router


# ---------------------------------------------------------------------------
# Provenance ("No quote, no edge") tests
# ---------------------------------------------------------------------------


def test_verify_quote_handles_exact_and_typography_variants():
    chunk = "Attention\n  scales   dot\u2013products by \u201c1 / sqrt(d_k)\u201d to stabilize gradients."
    assert verify_quote_in_text('scales dot-products by "1 / sqrt(d_k)"', chunk) is True
    assert verify_quote_in_text("completely fabricated quote", chunk) is False
    # Too short (<12 chars) must be rejected even if present
    assert verify_quote_in_text("Attention", chunk) is False


def test_validate_proposed_bridges_rejects_hallucinations_and_missing_chunks():
    c_new = NoteChunk(
        chunk_id="chunk-new-1",
        note_id="note-new",
        note_title="Transformers",
        content="Scaled dot-product attention divides scores by sqrt(d_k) before softmax.",
    )
    c_old = NoteChunk(
        chunk_id="chunk-old-1",
        note_id="note-old",
        note_title="Optimization",
        content="Large pre-activation logits saturate softmax gradients toward zero.",
    )
    chunks_by_id = {c_new.chunk_id: c_new, c_old.chunk_id: c_old}

    valid = ProposedBridge(
        source_concept="Scaled Attention",
        target_concept="Softmax Saturation",
        relationship_type="PREREQUISITE_OF",
        title="Why scaling prevents softmax saturation",
        explanation="Dividing by sqrt(d_k) keeps logits out of softmax's flat regime.",
        source_chunk_id="chunk-new-1",
        source_quote="divides scores by sqrt(d_k) before softmax",
        target_chunk_id="chunk-old-1",
        target_quote="Large pre-activation logits saturate softmax gradients",
    )
    bad_quote = valid.model_copy(update={"target_quote": "this quote was hallucinated"})
    missing_chunk = valid.model_copy(update={"source_chunk_id": "missing-id"})
    same_note = valid.model_copy(update={"target_chunk_id": "chunk-new-1", "target_quote": valid.source_quote})

    report = validate_proposed_bridges([valid, bad_quote, missing_chunk, same_note], chunks_by_id)
    assert len(report.accepted) == 1
    assert [r.reason for r in report.rejected] == [
        "unverified_target_quote",
        "missing_source_chunk",
        "same_note_bridge_not_cross_note",
    ]


# ---------------------------------------------------------------------------
# Durable Queue lifecycle tests (claim, no double-claim, backoff, dead_letter)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_queue_single_claim_and_complete():
    q = InMemoryJobQueue()
    job = await q.enqueue("user-1", "note.ingested", {"note_id": "n-1"})
    assert job.status == "pending"

    c1, c2 = await asyncio.gather(q.claim_next("worker-a"), q.claim_next("worker-b"))
    claimed = [c for c in (c1, c2) if c is not None]
    assert len(claimed) == 1
    assert claimed[0].id == job.id
    assert claimed[0].status == "running"
    assert claimed[0].attempts == 1

    await q.complete(job.id)
    jobs = await q.list_jobs("user-1")
    assert jobs[0].status == "completed"


@pytest.mark.asyncio
async def test_job_queue_retries_then_dead_letters():
    q = InMemoryJobQueue()
    job = await q.enqueue("user-1", "note.ingested", {"note_id": "n-1"}, max_attempts=2)

    first = await q.claim_next("w1")
    assert first is not None
    after_fail_1 = await q.fail(first.id, "transient timeout", backoff_seconds=0.0)
    assert after_fail_1.status == "pending"
    assert after_fail_1.last_error == "transient timeout"

    # Future run_after must block immediate claim
    future_job = await q.enqueue(
        "user-2",
        "note.ingested",
        {"note_id": "n-2"},
        run_after=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    second = await q.claim_next("w1")
    assert second is not None and second.id == job.id
    assert second.id != future_job.id

    after_fail_2 = await q.fail(second.id, "permanent error", backoff_seconds=0.0)
    assert after_fail_2.status == "dead_letter"
    assert await q.claim_next("w1") is None


# ---------------------------------------------------------------------------
# End-to-end note.ingested worker loop tests
# ---------------------------------------------------------------------------


class _FakeMemory:
    def __init__(self, chunks: list[NoteChunk]):
        self._chunks = chunks

    async def fetch_note_and_related_chunks(self, user_id, note_id, concept_names, *, limit=12):
        return self._chunks


class _FakeLLM:
    def __init__(self, batch: BridgeProposalBatch | None = None, error: Exception | None = None):
        self._batch = batch
        self._error = error

    async def propose_bridges(self, **kwargs):
        if self._error is not None:
            raise self._error
        return self._batch, {"model": "gemini-3.5-flash-lite", "input_tokens": 120, "output_tokens": 45}


@pytest.mark.asyncio
async def test_worker_note_ingested_filters_ungrounded_and_publishes_verified_insight():
    q = InMemoryJobQueue()
    insights = InMemoryInsightStore()
    runs = InMemoryRunLogger()

    chunks = [
        NoteChunk(
            chunk_id="c-new",
            note_id="note-1",
            note_title="Backprop Notes",
            content="Residual skip connections preserve gradient magnitude across deep layers.",
        ),
        NoteChunk(
            chunk_id="c-old",
            note_id="note-0",
            note_title="Vanishing Gradients",
            content="Repeated sigmoid derivatives shrink gradients exponentially in deep networks.",
        ),
    ]
    batch = BridgeProposalBatch(
        bridges=[
            ProposedBridge(
                source_concept="Residual Connections",
                target_concept="Vanishing Gradients",
                relationship_type="CONTRASTS_WITH",
                title="Skip connections counter vanishing gradients",
                explanation="Skip paths keep gradients flowing instead of shrinking exponentially.",
                source_chunk_id="c-new",
                source_quote="preserve gradient magnitude across deep layers",
                target_chunk_id="c-old",
                target_quote="shrink gradients exponentially in deep networks",
            ),
            ProposedBridge(
                source_concept="Fake Concept",
                target_concept="Vanishing Gradients",
                relationship_type="RELATED_TO",
                title="Hallucinated link",
                explanation="Should never be stored.",
                source_chunk_id="c-new",
                source_quote="this quote does not exist anywhere",
                target_chunk_id="c-old",
                target_quote="shrink gradients exponentially in deep networks",
            ),
        ]
    )

    worker = AgentWorker(q, backoff_base_s=0.0)
    memory = _FakeMemory(chunks)
    llm = _FakeLLM(batch=batch)
    worker.register(
        "note.ingested",
        lambda job: handle_note_ingested(job, memory=memory, llm=llm, insights=insights, runs=runs),
    )

    enqueued = await q.enqueue(
        "user-1",
        "note.ingested",
        {"note_id": "note-1", "note_title": "Backprop Notes", "concept_names": ["Residual Connections"]},
    )
    processed = await worker.process_one()
    assert processed is True

    stored_insights = await insights.list_for_user("user-1")
    assert len(stored_insights) == 1
    assert stored_insights[0].insight_type == "conflict"
    assert stored_insights[0].title == "Skip connections counter vanishing gradients"
    assert len(stored_insights[0].source_quotes) == 2

    recorded_runs = await runs.list_for_user("user-1")
    assert len(recorded_runs) == 1
    assert recorded_runs[0].status == "completed"
    assert recorded_runs[0].input_tokens == 120
    assert recorded_runs[0].tool_calls[0]["accepted"] == 1
    assert recorded_runs[0].tool_calls[0]["rejected"] == 1

    jobs = await q.list_jobs("user-1")
    assert jobs[0].id == enqueued.id
    assert jobs[0].status == "completed"


@pytest.mark.asyncio
async def test_worker_surfaces_llm_errors_without_silent_success():
    q = InMemoryJobQueue()
    insights = InMemoryInsightStore()
    runs = InMemoryRunLogger()

    chunks = [
        NoteChunk(chunk_id="c1", note_id="n1", note_title="A", content="Alpha content here."),
        NoteChunk(chunk_id="c2", note_id="n2", note_title="B", content="Beta content here."),
    ]
    worker = AgentWorker(q, backoff_base_s=0.0)
    memory = _FakeMemory(chunks)
    llm = _FakeLLM(error=RuntimeError("Gemini 503 unavailable"))
    worker.register(
        "note.ingested",
        lambda job: handle_note_ingested(job, memory=memory, llm=llm, insights=insights, runs=runs),
    )

    await q.enqueue("user-1", "note.ingested", {"note_id": "n1"}, max_attempts=1)
    assert await worker.process_one() is True

    jobs = await q.list_jobs("user-1")
    assert jobs[0].status == "dead_letter"
    assert "503" in (jobs[0].last_error or "")

    recorded_runs = await runs.list_for_user("user-1")
    assert len(recorded_runs) == 1
    assert recorded_runs[0].status == "failed"
    assert "503" in (recorded_runs[0].error or "")
    assert await insights.list_for_user("user-1") == []


# ---------------------------------------------------------------------------
# FastAPI /api/v2/agent router tests (offline dependency overrides)
# ---------------------------------------------------------------------------


def test_agent_v2_router_endpoints():
    q = InMemoryJobQueue()
    insights = InMemoryInsightStore()
    runs = InMemoryRunLogger()

    app.dependency_overrides[get_current_user] = lambda: {"id": "user-123"}
    app.dependency_overrides[agent_v2_router.get_job_queue] = lambda: q
    app.dependency_overrides[agent_v2_router.get_insight_store] = lambda: insights
    app.dependency_overrides[agent_v2_router.get_run_logger] = lambda: runs

    try:
        client = TestClient(app)

        resp = client.post(
            "/api/v2/agent/triggers/note-ingested",
            json={"note_id": "note-99", "note_title": "Test Note", "concept_names": ["Graphs"]},
        )
        assert resp.status_code == 202
        job_data = resp.json()
        assert job_data["job_type"] == "note.ingested"
        assert job_data["status"] == "pending"

        jobs_resp = client.get("/api/v2/agent/jobs")
        assert jobs_resp.status_code == 200
        assert jobs_resp.json()["total"] == 1

        # Seed one insight + run via worker loop
        chunks = [
            NoteChunk(
                chunk_id="cn",
                note_id="note-99",
                note_title="Test Note",
                content="Graph traversal explores multi-hop dependencies between concepts.",
            ),
            NoteChunk(
                chunk_id="co",
                note_id="note-10",
                note_title="Older Note",
                content="Breadth-first search visits k-hop neighbors systematically.",
            ),
        ]
        batch = BridgeProposalBatch(
            bridges=[
                ProposedBridge(
                    source_concept="Graph Traversal",
                    target_concept="BFS",
                    relationship_type="RELATED_TO",
                    title="Traversal generalizes BFS",
                    explanation="Multi-hop traversal builds directly on BFS neighbor expansion.",
                    source_chunk_id="cn",
                    source_quote="explores multi-hop dependencies between concepts",
                    target_chunk_id="co",
                    target_quote="visits k-hop neighbors systematically",
                )
            ]
        )
        worker = AgentWorker(q, backoff_base_s=0.0)
        worker.register(
            "note.ingested",
            lambda j: handle_note_ingested(
                j, memory=_FakeMemory(chunks), llm=_FakeLLM(batch=batch), insights=insights, runs=runs
            ),
        )
        assert asyncio.run(worker.process_one()) is True

        ins_resp = client.get("/api/v2/agent/insights?status=active")
        assert ins_resp.status_code == 200
        assert ins_resp.json()["total"] == 1
        insight_id = ins_resp.json()["insights"][0]["id"]

        dismiss_resp = client.post(f"/api/v2/agent/insights/{insight_id}/dismiss")
        assert dismiss_resp.status_code == 200
        assert dismiss_resp.json()["status"] == "dismissed"

        active_after = client.get("/api/v2/agent/insights?status=active")
        assert active_after.json()["total"] == 0

        runs_resp = client.get("/api/v2/agent/runs")
        assert runs_resp.status_code == 200
        assert runs_resp.json()["total"] == 1
        assert runs_resp.json()["runs"][0]["status"] == "completed"
    finally:
        app.dependency_overrides.clear()
