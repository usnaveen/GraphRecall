"""100% offline unit & API tests for Always-On Agent v2 (no live Postgres, Neo4j, or Gemini)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.agent_v2.adapters import AsyncRateLimiter
from backend.agent_v2.job_queue import (
    InMemoryInsightStore,
    InMemoryJobQueue,
    InMemoryRunLogger,
)
from backend.agent_v2.protocols import (
    BridgeProposalBatch,
    ConceptReviewContext,
    DailyBriefingDraft,
    NoteChunk,
    ProposedBridge,
    RemedialDiagnosis,
    UserLearningDigest,
)
from backend.agent_v2.provenance import (
    validate_proposed_bridges,
    verify_quote_in_text,
)
from backend.agent_v2.worker import (
    AgentWorker,
    handle_heartbeat_daily,
    handle_note_ingested,
    handle_review_lapsed,
)
from backend.auth.middleware import get_current_user
from backend.main import app
from backend.routers import agent_v2 as agent_v2_router
from backend.routers import ingest_v2 as ingest_v2_router


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
    def __init__(
        self,
        chunks: list[NoteChunk] | None = None,
        review_ctx: ConceptReviewContext | None = None,
        digest: UserLearningDigest | None = None,
    ):
        self._chunks = chunks or []
        self._review_ctx = review_ctx
        self._digest = digest

    async def fetch_note_and_related_chunks(self, user_id, note_id, concept_names, *, limit=12):
        return self._chunks

    async def fetch_concept_review_context(self, user_id, concept_id, concept_name, *, note_id=None, limit=6):
        return self._review_ctx or ConceptReviewContext(concept_id=concept_id, concept_name=concept_name)

    async def fetch_learning_digest(self, user_id, *, window_days=7, limit=8):
        return self._digest or UserLearningDigest()


class _FakeLLM:
    def __init__(
        self,
        batch: BridgeProposalBatch | None = None,
        diagnosis: RemedialDiagnosis | None = None,
        briefing: DailyBriefingDraft | None = None,
        error: Exception | None = None,
    ):
        self._batch = batch
        self._diagnosis = diagnosis
        self._briefing = briefing
        self._error = error

    def _meta(self) -> dict:
        return {"model": "gemini-3.5-flash-lite", "input_tokens": 120, "output_tokens": 45}

    async def propose_bridges(self, **kwargs):
        if self._error is not None:
            raise self._error
        return self._batch, self._meta()

    async def diagnose_review_lapse(self, **kwargs):
        if self._error is not None:
            raise self._error
        return self._diagnosis, self._meta()

    async def compose_daily_briefing(self, **kwargs):
        if self._error is not None:
            raise self._error
        return self._briefing, self._meta()


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


# ---------------------------------------------------------------------------
# GR2-01 Review Fixes & GR2-02 Loop Tests (100% Offline)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_queue_crash_recovery_reclaims_expired_lease_and_dead_letters_exhausted():
    now = [datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)]
    q = InMemoryJobQueue(clock=lambda: now[0])

    # Job 1: worker-1 claims and crashes; worker-2 reclaims after lease expires and completes
    job1 = await q.enqueue("user-1", "note.ingested", {"note_id": "n-crash"}, max_attempts=3)
    claimed_1 = await q.claim_next("worker-1", lease_seconds=60.0)
    assert claimed_1 is not None and claimed_1.id == job1.id and claimed_1.attempts == 1

    # Before lease expiry, worker-2 must NOT steal the running job
    now[0] += timedelta(seconds=30)
    assert await q.claim_next("worker-2", lease_seconds=60.0) is None

    # After lease expiry (>60s), worker-2 reclaims cleanly with attempts == 2
    now[0] += timedelta(seconds=35)
    reclaimed = await q.claim_next("worker-2", lease_seconds=60.0)
    assert reclaimed is not None and reclaimed.id == job1.id
    assert reclaimed.attempts == 2
    assert reclaimed.locked_by == "worker-2"
    await q.complete(reclaimed.id)
    assert (await q.list_jobs("user-1"))[0].status == "completed"

    # Job 2: max_attempts=2, crashes twice -> expired lease dead-letters it permanently
    job2 = await q.enqueue("user-2", "note.ingested", {"note_id": "n-dlq"}, max_attempts=2)
    assert (await q.claim_next("w-a", lease_seconds=60.0)).attempts == 1
    now[0] += timedelta(seconds=61)
    assert (await q.claim_next("w-b", lease_seconds=60.0)).attempts == 2
    now[0] += timedelta(seconds=61)
    assert await q.claim_next("w-c", lease_seconds=60.0) is None
    dlq_jobs = await q.list_jobs("user-2", status="dead_letter")
    assert len(dlq_jobs) == 1 and dlq_jobs[0].id == job2.id


def test_verify_quote_rejects_stopword_only_and_trivial_quotes():
    chunk = "The patient received in the and of the standard intravenous saline protocol yesterday."
    assert verify_quote_in_text("the patient ", chunk) is False
    assert verify_quote_in_text("in the and of the", chunk) is False
    assert verify_quote_in_text("standard intravenous saline protocol", chunk) is True


@pytest.mark.asyncio
async def test_async_rate_limiter_enforces_rpm_spacing():
    fake_now = [100.0]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        fake_now[0] += seconds

    limiter = AsyncRateLimiter(max_rpm=12.0, clock=lambda: fake_now[0], sleeper=fake_sleep)
    assert await limiter.acquire() == 0.0
    assert await limiter.acquire() == pytest.approx(5.0)
    fake_now[0] += 2.0  # 2s already elapsed before 3rd call
    assert await limiter.acquire() == pytest.approx(3.0)
    assert sleeps == pytest.approx([5.0, 3.0])


@pytest.mark.asyncio
async def test_worker_review_lapsed_verified_and_ungrounded_rejection():
    q = InMemoryJobQueue()
    insights = InMemoryInsightStore()
    runs = InMemoryRunLogger()

    chunk = NoteChunk(
        chunk_id="c-grad",
        note_id="note-opt",
        note_title="Convex Optimization",
        content="Step size eta must remain below 2/L for L-smooth convex functions to guarantee descent.",
    )
    ctx = ConceptReviewContext(
        concept_id="concept-gd",
        concept_name="Gradient Descent Step Size",
        prerequisites=[],
        has_prerequisite_edges=False,
        chunks=[chunk],
    )

    good_diag = RemedialDiagnosis(
        title="Review step-size stability bound",
        explanation="Divergence happens when step size exceeds the smoothness bound 2/L.",
        missing_prerequisite=None,
        source_chunk_id="c-grad",
        source_quote="Step size eta must remain below 2/L",
        study_prompt="What upper bound on learning rate guarantees descent for L-smooth functions?",
    )
    worker = AgentWorker(q, backoff_base_s=0.0)
    worker.register(
        "review.lapsed",
        lambda j: handle_review_lapsed(
            j, memory=_FakeMemory(review_ctx=ctx), llm=_FakeLLM(diagnosis=good_diag), insights=insights, runs=runs
        ),
    )
    await q.enqueue("user-1", "review.lapsed", {"concept_id": "concept-gd", "concept_name": "Gradient Descent Step Size", "lapse_count": 2})
    assert await worker.process_one() is True

    saved = await insights.list_for_user("user-1")
    assert len(saved) == 1
    assert saved[0].insight_type == "remedial"
    assert saved[0].action_payload["prerequisite_graph_available"] is False
    assert saved[0].source_quotes[0].chunk_id == "c-grad"

    # Now test hallucinated quote rejection
    bad_diag = good_diag.model_copy(update={"source_quote": "fabricated non existent quote here"})
    insights2 = InMemoryInsightStore()
    worker2 = AgentWorker(q, backoff_base_s=0.0)
    worker2.register(
        "review.lapsed",
        lambda j: handle_review_lapsed(
            j, memory=_FakeMemory(review_ctx=ctx), llm=_FakeLLM(diagnosis=bad_diag), insights=insights2, runs=runs
        ),
    )
    await q.enqueue("user-1", "review.lapsed", {"concept_id": "concept-gd", "concept_name": "Gradient Descent Step Size"})
    assert await worker2.process_one() is True
    assert await insights2.list_for_user("user-1") == []


@pytest.mark.asyncio
async def test_worker_heartbeat_daily_briefing_and_empty_skip():
    q = InMemoryJobQueue()
    insights = InMemoryInsightStore()
    runs = InMemoryRunLogger()

    chunk = NoteChunk(
        chunk_id="c-attn",
        note_id="note-attn",
        note_title="Transformers",
        content="Multi-head attention projects queries, keys, and values into distinct representation subspaces.",
    )
    digest = UserLearningDigest(
        recent_notes_count=2,
        due_concepts=["Multi-Head Attention", "LayerNorm"],
        lapsed_concepts=["Multi-Head Attention"],
        sample_chunks=[chunk],
    )
    draft = DailyBriefingDraft(
        title="Daily Focus: Multi-Head Attention Subspaces",
        summary_md="You added 2 notes this week; revisit multi-head projections before LayerNorm.",
        priority_concepts=["Multi-Head Attention"],
        cited_chunk_id="c-attn",
        cited_quote="projects queries, keys, and values into distinct representation subspaces",
    )

    worker = AgentWorker(q, backoff_base_s=0.0)
    worker.register(
        "heartbeat.daily",
        lambda j: handle_heartbeat_daily(
            j, memory=_FakeMemory(digest=digest), llm=_FakeLLM(briefing=draft), insights=insights, runs=runs
        ),
    )
    await q.enqueue("user-1", "heartbeat.daily", {"window_days": 7, "max_items": 5})
    assert await worker.process_one() is True

    briefings = await insights.list_for_user("user-1")
    assert len(briefings) == 1
    assert briefings[0].insight_type == "briefing"
    assert briefings[0].source_quotes[0].chunk_id == "c-attn"

    # Empty user digest skips LLM cleanly
    worker_empty = AgentWorker(q, backoff_base_s=0.0)
    worker_empty.register(
        "heartbeat.daily",
        lambda j: handle_heartbeat_daily(
            j,
            memory=_FakeMemory(digest=UserLearningDigest()),
            llm=_FakeLLM(error=AssertionError("LLM must not be called for empty digest")),
            insights=insights,
            runs=runs,
        ),
    )
    await q.enqueue("user-2", "heartbeat.daily", {"window_days": 7})
    assert await worker_empty.process_one() is True
    assert await insights.list_for_user("user-2") == []


def test_ingest_v2_auto_enqueues_note_ingested_job(monkeypatch):
    q = InMemoryJobQueue()

    class _FakePg:
        async def execute_query(self, query, params=None):
            return []

    async def _fake_pg():
        return _FakePg()

    async def _fake_run_ingestion(**kwargs):
        return {
            "note_id": "note-new-1",
            "status": "completed",
            "concepts": [{"name": "Graph Traversal"}, {"name": "BFS"}],
            "concept_ids": ["c-1", "c-2"],
            "flashcard_ids": ["f-1"],
            "thread_id": "thread-offline-1",
        }

    async def _noop_scan(*args, **kwargs):
        return None

    async def _noop_comm(*args, **kwargs):
        return None

    async def _fake_queue():
        return q

    monkeypatch.setenv("QUOTA_INGEST_PER_DAY", "0")
    monkeypatch.setattr("backend.db.postgres_client.get_postgres_client", _fake_pg)
    monkeypatch.setattr(ingest_v2_router, "get_postgres_client", _fake_pg)
    monkeypatch.setattr(ingest_v2_router, "run_ingestion", _fake_run_ingestion)
    monkeypatch.setattr(ingest_v2_router.scanner_agent, "scan_and_save", _noop_scan)
    monkeypatch.setattr(ingest_v2_router, "_recompute_communities", _noop_comm)
    monkeypatch.setattr(agent_v2_router, "get_job_queue", _fake_queue)
    app.dependency_overrides[get_current_user] = lambda: {"id": "user-ingest-1"}

    try:
        client = TestClient(app)
        resp = client.post(
            "/api/v2/ingest",
            json={"content": "BFS visits graph neighbors level by level.", "title": "Graph Search", "skip_review": True},
        )
        assert resp.status_code == 200
        assert resp.json()["note_id"] == "note-new-1"

        jobs = asyncio.run(q.list_jobs("user-ingest-1"))
        assert len(jobs) == 1
        assert jobs[0].job_type == "note.ingested"
        assert jobs[0].payload["note_id"] == "note-new-1"
        assert jobs[0].payload["note_title"] == "Graph Search"
        assert jobs[0].payload["concept_names"] == ["Graph Traversal", "BFS"]
    finally:
        app.dependency_overrides.clear()


def test_agent_v2_router_new_triggers_act_and_feed_cards():
    q = InMemoryJobQueue()
    insights = InMemoryInsightStore()
    runs = InMemoryRunLogger()

    chunk = NoteChunk(
        chunk_id="c-feed",
        note_id="n-feed",
        note_title="Optimization Notes",
        content="Adam decouples momentum estimates from per-parameter adaptive learning rates.",
    )
    diag = RemedialDiagnosis(
        title="Revisit Adam adaptive scaling",
        explanation="Check how second-moment bias correction prevents early step collapse.",
        source_chunk_id="c-feed",
        source_quote="decouples momentum estimates from per-parameter adaptive learning rates",
        study_prompt="Why does Adam include bias correction in early steps?",
    )
    ctx = ConceptReviewContext(concept_id="adam", concept_name="Adam Optimizer", chunks=[chunk])

    app.dependency_overrides[get_current_user] = lambda: {"id": "user-feed-1"}
    app.dependency_overrides[agent_v2_router.get_job_queue] = lambda: q
    app.dependency_overrides[agent_v2_router.get_insight_store] = lambda: insights
    app.dependency_overrides[agent_v2_router.get_run_logger] = lambda: runs

    try:
        client = TestClient(app)

        r1 = client.post(
            "/api/v2/agent/triggers/review-lapsed",
            json={"concept_id": "adam", "concept_name": "Adam Optimizer", "lapse_count": 3},
        )
        assert r1.status_code == 202 and r1.json()["job_type"] == "review.lapsed"

        r2 = client.post("/api/v2/agent/triggers/briefing", json={"window_days": 5, "max_items": 4})
        assert r2.status_code == 202 and r2.json()["job_type"] == "heartbeat.daily"

        # Process the review.lapsed job into an insight
        worker = AgentWorker(q, backoff_base_s=0.0)
        worker.register(
            "review.lapsed",
            lambda j: handle_review_lapsed(
                j, memory=_FakeMemory(review_ctx=ctx), llm=_FakeLLM(diagnosis=diag), insights=insights, runs=runs
            ),
        )
        assert asyncio.run(worker.process_one()) is True

        feed_resp = client.get("/api/v2/agent/feed-cards")
        assert feed_resp.status_code == 200
        cards = feed_resp.json()["cards"]
        assert len(cards) == 1
        assert cards[0]["card_type"] == "agent_insight"
        assert cards[0]["insight_type"] == "remedial"

        act_resp = client.post(f"/api/v2/agent/insights/{cards[0]['id']}/act")
        assert act_resp.status_code == 200
        assert act_resp.json()["status"] == "acted"

        assert client.get("/api/v2/agent/feed-cards").json()["total"] == 0
    finally:
        app.dependency_overrides.clear()
