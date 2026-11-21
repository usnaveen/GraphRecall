"""Rate limiting (token bucket) and daily LLM quotas (real Postgres scratch database)."""

import asyncio
import uuid

import pytest

from backend.tests.test_migrate import scratch_db  # noqa: F401  (shared real-Postgres fixture)


def test_token_bucket_burst_then_refill():
    from backend.middleware.rate_limit import RateLimitMiddleware

    rl = RateLimitMiddleware(app=None, per_min=60, burst=3)       # 1 token/s, burst 3
    assert [rl.allow("k", now=0.0)[0] for _ in range(4)] == [True, True, True, False]
    ok, retry = rl.allow("k", now=0.5)
    assert not ok and 0 < retry <= 1
    assert rl.allow("k", now=1.6)[0]                                 # refilled
    assert rl.allow("other", now=0.0)[0]                             # per-client buckets


@pytest.mark.asyncio
async def test_daily_quota_enforced_atomically_and_per_user(scratch_db, monkeypatch):
    from backend.db import migrate as M
    from backend.services.quota import QuotaExceeded, consume

    pg, _ = scratch_db
    await M.migrate(pg)
    ids = []
    for tag in ("a", "b"):
        e = f"quota-{tag}-{uuid.uuid4().hex[:6]}@example.invalid"
        await pg.execute_update("INSERT INTO users (email, name) VALUES (:e, :n)", {"e": e, "n": tag})
        ids.append(str((await pg.execute_query("SELECT id FROM users WHERE email = :e", {"e": e}))[0]["id"]))
    a, b = ids
    monkeypatch.setenv("QUOTA_INGEST_PER_DAY", "5")

    # 8 concurrent attempts at a limit of 5: exactly 5 succeed (check + increment are one statement)
    results = await asyncio.gather(*(consume(pg, a, "ingest") for _ in range(8)), return_exceptions=True)
    assert sum(not isinstance(r, Exception) for r in results) == 5
    assert all(isinstance(r, QuotaExceeded) for r in results if isinstance(r, Exception))
    assert await consume(pg, b, "ingest") == 1                        # another user is unaffected
    monkeypatch.setenv("QUOTA_INGEST_PER_DAY", "0")
    assert await consume(pg, a, "ingest") == 0                        # 0 disables the quota
