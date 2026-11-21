"""Offline unit tests for Option C worker contract, P3 durable jobs, and R2/S3 storage."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.agent_v2.enqueue import enqueue_durable_job
from backend.agent_v2.job_queue import InMemoryJobQueue, InMemoryRunLogger
from backend.agent_v2.worker import (
    AgentWorker,
    handle_community_recompute,
    handle_embeddings_retry,
    handle_feed_buffer_ensure,
    handle_quiz_scan,
)
from backend.services.storage_service import MAX_FILE_SIZE_BYTES, StorageService


@pytest.mark.asyncio
async def test_worker_heartbeat_and_graceful_sigterm_releases_slow_job(tmp_path):
    hb = tmp_path / "worker.alive"
    q = InMemoryJobQueue()

    # 1. Fast job finishes within grace window on SIGTERM -> completed
    fast_job = await q.enqueue("u1", "fast.job", {})
    worker = AgentWorker(
        q,
        worker_id="w-fast",
        poll_interval_s=0.05,
        heartbeat_path=str(hb),
        shutdown_grace_seconds=0.5,
    )
    stop_fast = asyncio.Event()

    async def _fast_handler(_job):
        await asyncio.sleep(0.03)

    worker.register("fast.job", _fast_handler)
    worker.touch_heartbeat()
    assert hb.exists()

    async def _trigger_fast_stop():
        await asyncio.sleep(0.01)
        stop_fast.set()

    stopper_task = asyncio.create_task(_trigger_fast_stop())
    did_work = await worker.process_one(stop_event=stop_fast)
    await stopper_task
    assert did_work is True
    assert (await q.list_jobs("u1"))[0].status == "completed"

    # 2. Slow job exceeds grace window on SIGTERM -> canceled & lease released back to pending
    q2 = InMemoryJobQueue()
    slow_job = await q2.enqueue("u1", "slow.job", {}, max_attempts=3)
    worker2 = AgentWorker(
        q2,
        worker_id="w-slow",
        poll_interval_s=0.05,
        heartbeat_path=str(hb),
        shutdown_grace_seconds=0.03,
    )
    stop_slow = asyncio.Event()

    async def _slow_handler(_job):
        await asyncio.sleep(5.0)

    worker2.register("slow.job", _slow_handler)

    async def _trigger_slow_stop():
        await asyncio.sleep(0.01)
        stop_slow.set()

    stopper_task2 = asyncio.create_task(_trigger_slow_stop())
    did_work2 = await worker2.process_one(stop_event=stop_slow)
    await stopper_task2
    assert did_work2 is True

    jobs = await q2.list_jobs("u1")
    assert jobs[0].id == slow_job.id
    assert jobs[0].status == "pending"
    assert jobs[0].locked_by is None
    assert jobs[0].attempts == 0


@pytest.mark.asyncio
async def test_p3_durable_handlers_and_deduplication():
    q = InMemoryJobQueue()
    runs = InMemoryRunLogger()

    # Deduplication prevents multiple pending jobs within window
    j1 = await enqueue_durable_job(
        "u1", "community.recompute", {"note_id": "n1"}, dedupe_window_seconds=120, job_queue=q
    )
    j2 = await enqueue_durable_job(
        "u1", "community.recompute", {"note_id": "n2"}, dedupe_window_seconds=120, job_queue=q
    )
    assert j1 is not None
    assert j2 is None

    # 1. community.recompute
    comm = MagicMock()

    async def _recompute(uid):
        return {"communities": 3, "user_id": uid}

    comm.recompute_communities = _recompute
    await handle_community_recompute(j1, community_service=comm, runs=runs)

    # 2. embeddings.retry raises when still_missing > 0 so job queue retries with backoff
    emb_job = await enqueue_durable_job("u1", "embeddings.retry", {"note_id": "n1"}, job_queue=q)
    assert emb_job is not None

    async def _reembed_partial(_uid, _nid):
        return {"still_missing": 2}

    with pytest.raises(RuntimeError, match="still missing"):
        await handle_embeddings_retry(emb_job, reembed_fn=_reembed_partial, runs=runs)

    async def _reembed_ok(_uid, _nid):
        return {"still_missing": 0, "updated": 2}

    res = await handle_embeddings_retry(emb_job, reembed_fn=_reembed_ok, runs=runs)
    assert res["still_missing"] == 0

    # 3. quiz.scan loads note content scoped by user_id when not in payload
    scanned: list[tuple[str, str, str]] = []

    class _FakePg:
        async def execute_query(self, query, params=None):
            assert "user_id" in query
            return [{"content": "Attention scales dot products by sqrt(d_k)."}]

    class _FakeScanner:
        async def scan_and_save(self, content, note_id, user_id):
            scanned.append((content, note_id, user_id))

    scan_job = await enqueue_durable_job(
        "u1", "quiz.scan", {"note_id": "00000000-0000-0000-0000-000000000001"}, job_queue=q
    )
    assert scan_job is not None
    await handle_quiz_scan(scan_job, pg=_FakePg(), scanner=_FakeScanner(), runs=runs)
    assert len(scanned) == 1
    assert "dot products" in scanned[0][0]

    # 4. feed.buffer_ensure
    buffered: list[str] = []

    class _FakeFeed:
        async def ensure_weekly_buffer(self, user_id):
            buffered.append(user_id)

    buf_job = await enqueue_durable_job(
        "u1", "feed.buffer_ensure", {"trigger": "feed_get"}, dedupe_window_seconds=3600, job_queue=q
    )
    assert buf_job is not None
    await handle_feed_buffer_ensure(buf_job, feed_service=_FakeFeed(), runs=runs)
    assert buffered == ["u1"]


@pytest.mark.asyncio
async def test_storage_service_r2_pdf_and_prod_fail_fast(monkeypatch, tmp_path):
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("R2_BUCKET_NAME", "gr-media")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "sk")
    monkeypatch.setenv("R2_PUBLIC_URL_BASE", "https://cdn.example.com")

    storage = StorageService()
    assert storage.is_configured() is True
    assert storage.endpoint_url == "https://acct123.r2.cloudflarestorage.com"
    assert storage.region == "auto"

    # PDF up to 50 MB accepted; images > 10 MB rejected
    ok_pdf, _ = storage.validate_file("application/pdf", MAX_FILE_SIZE_BYTES + 1024)
    assert ok_pdf is True
    ok_img, msg_img = storage.validate_file("image/png", MAX_FILE_SIZE_BYTES + 1024)
    assert ok_img is False and "Maximum" in msg_img

    mock_s3 = MagicMock()
    storage.s3_client = mock_s3
    url = await storage.upload_file(b"%PDF-1.4...", "notes.pdf", "application/pdf", "u1")
    assert url.startswith("https://cdn.example.com/uploads/u1/")
    assert mock_s3.put_object.call_count == 1
    deleted = await storage.delete_file(url)
    assert deleted is True
    assert mock_s3.delete_object.call_count == 1

    # Unconfigured fails in production and falls back locally in development
    for key in (
        "R2_ACCOUNT_ID",
        "R2_ENDPOINT_URL",
        "S3_ENDPOINT_URL",
        "R2_ACCESS_KEY_ID",
        "S3_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "S3_SECRET_ACCESS_KEY",
        "R2_PUBLIC_URL_BASE",
        "S3_PUBLIC_URL_BASE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LOCAL_UPLOAD_DIR", str(tmp_path / "uploads"))

    monkeypatch.setenv("ENVIRONMENT", "development")
    dev_storage = StorageService()
    assert dev_storage.is_configured() is False
    local_url = await dev_storage.upload_file(b"png", "a.png", "image/png", "u1")
    assert local_url.startswith("file://")
    assert await dev_storage.delete_file(local_url) is True

    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="production"):
        await dev_storage.upload_file(b"png", "a.png", "image/png", "u1")
