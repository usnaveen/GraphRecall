"""Pure-unit tests for reliability, security, and CI hardening fixes."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from backend.auth import google_oauth, sessions
from backend.middleware.rate_limit import RateLimitMiddleware
from backend.services.grounding_guard import AsyncCircuitBreaker
from backend.services.ingestion import embedding_service as es
from backend.services.spaced_repetition import SpacedRepetitionService


class _HttpStatusError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message or f"HTTP {status_code}")
        self.status_code = status_code


class _SessionFakePG:
    """Fake PG supporting async with pg.session() as session for batch cache-write assertions."""

    def __init__(self, initial_rows: dict[str, list[float]] | None = None) -> None:
        self.rows: dict[str, list[float]] = dict(initial_rows or {})
        self.session_entries = 0
        self.commits = 0
        self.rollbacks = 0
        self.executed: list[tuple[str, dict]] = []

    async def execute_query(self, query: str, params: dict | None = None):
        keys = (params or {}).get("keys") or []
        return [{"key": k, "embedding": self.rows[k]} for k in keys if k in self.rows]

    @asynccontextmanager
    async def session(self):
        self.session_entries += 1

        class _Sess:
            def __init__(self, outer: _SessionFakePG) -> None:
                self._outer = outer

            async def execute(self, stmt, params=None):
                self._outer.executed.append((str(stmt), dict(params or {})))

        try:
            yield _Sess(self)
            self.commits += 1
        except Exception:
            self.rollbacks += 1
            raise


class _FakeEmbedder:
    model = "gemini-embedding-001"

    def __init__(self, handler=None, query_handler=None) -> None:
        self.doc_calls: list[list[str]] = []
        self.query_calls: list[str] = []
        self._handler = handler
        self._query_handler = query_handler

    async def aembed_documents(self, texts: list[str], output_dimensionality: int = 768):
        self.doc_calls.append(list(texts))
        if self._handler is not None:
            return await self._handler(texts)
        return [[float(len(t))] * output_dimensionality for t in texts]

    async def aembed_query(self, text: str, output_dimensionality: int = 768):
        self.query_calls.append(text)
        if self._query_handler is not None:
            return await self._query_handler(text)
        return [1.0] * output_dimensionality


# ---- 1. EmbeddingService hardening -------------------------------------------


@pytest.mark.asyncio
async def test_embed_batch_deduplicates_identical_texts_uncached_and_cached():
    owner = "03fc4f19-f724-433e-96cf-7956f429f6d5"
    embedder = _FakeEmbedder()
    svc = es.EmbeddingService.__new__(es.EmbeddingService)
    svc.embedder = embedder
    svc.dims = 4
    svc._circuit_breaker = AsyncCircuitBreaker()

    # Uncached path: duplicates embedded once, mapped back cleanly
    out_uncached = await svc.embed_batch(["alpha", "beta", "alpha", "beta", "gamma"])
    assert embedder.doc_calls == [["alpha", "beta", "gamma"]]
    assert out_uncached == [
        [5.0, 5.0, 5.0, 5.0],
        [4.0, 4.0, 4.0, 4.0],
        [5.0, 5.0, 5.0, 5.0],
        [4.0, 4.0, 4.0, 4.0],
        [5.0, 5.0, 5.0, 5.0],
    ]

    # Cached path: duplicate misses in the same batch are embedded once and written in 1 session
    embedder.doc_calls.clear()
    pg = _SessionFakePG()
    with patch("backend.db.postgres_client.get_postgres_client", AsyncMock(return_value=pg)):
        out_cached = await svc.embed_batch(["delta", "epsilon", "delta"], owner=owner)

    assert embedder.doc_calls == [["delta", "epsilon"]]
    assert out_cached[0] == out_cached[2] == [5.0] * 4
    assert out_cached[1] == [7.0] * 4
    assert pg.session_entries == 1
    assert pg.commits == 1
    assert len(pg.executed) == 1
    sql, params = pg.executed[0]
    assert "INSERT INTO embedding_cache" in sql
    assert params["k_0"] != params["k_1"]
    assert "k_2" not in params


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
async def test_embedding_does_not_retry_non_retryable_4xx(monkeypatch, status_code: int):
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(es.asyncio, "sleep", fake_sleep)

    async def fail_4xx(_texts):
        raise _HttpStatusError(status_code, f"HTTP {status_code} client error")

    async def fail_query(_text):
        raise _HttpStatusError(status_code, f"HTTP {status_code} client error")

    embedder = _FakeEmbedder(handler=fail_4xx, query_handler=fail_query)
    svc = es.EmbeddingService.__new__(es.EmbeddingService)
    svc.embedder = embedder
    svc.dims = 4
    svc._circuit_breaker = AsyncCircuitBreaker()

    batch_out = await svc.embed_batch(["one", "two", "three"])
    query_out = await svc.embed_query("hello")

    assert len(embedder.doc_calls) == 1  # fail fast: no retries, no 1-by-1 fallback
    assert len(embedder.query_calls) == 1
    assert sleep_calls == []
    assert all(v == [] for v in batch_out)
    assert query_out == []
    # Non-retryable 4xx must not trip the circuit breaker
    assert svc._circuit_breaker.state == "closed"


@pytest.mark.asyncio
async def test_embedding_429_does_not_amplify_to_one_by_one_and_trips_breaker(monkeypatch):
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(es.asyncio, "sleep", fake_sleep)

    async def fail_429(_texts):
        raise _HttpStatusError(429, "429 Too Many Requests")

    embedder = _FakeEmbedder(handler=fail_429)
    svc = es.EmbeddingService.__new__(es.EmbeddingService)
    svc.embedder = embedder
    svc.dims = 4
    svc._circuit_breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout_s=30.0)

    texts = [f"chunk-{i}" for i in range(50)]
    out = await svc.embed_batch(texts)

    assert len(out) == 50
    assert all(v == [] for v in out)
    # 3 batch retries only (NEVER 3 + 50*3 = 153 amplification storm)
    assert len(embedder.doc_calls) == es.MAX_RETRIES
    assert sleep_calls == [1, 2]

    # Two more 429s reach threshold=5 and open the circuit breaker; subsequent calls hit 0 API calls
    await svc.embed_batch(["extra-1"])
    assert svc._circuit_breaker.state == "open"
    calls_before_open_reject = len(embedder.doc_calls)
    rejected = await svc.embed_batch(["extra-2", "extra-3"])
    assert len(embedder.doc_calls) == calls_before_open_reject
    assert all(v == [] for v in rejected)


@pytest.mark.asyncio
async def test_embedding_falls_back_one_by_one_only_on_payload_batch_errors(monkeypatch):
    monkeypatch.setattr(es.asyncio, "sleep", AsyncMock())

    async def fail_payload(texts):
        if len(texts) > 1:
            raise _HttpStatusError(413, "Request payload size exceeds batch limit")
        return [[9.0] * 4]

    embedder = _FakeEmbedder(handler=fail_payload)
    svc = es.EmbeddingService.__new__(es.EmbeddingService)
    svc.embedder = embedder
    svc.dims = 4
    svc._circuit_breaker = AsyncCircuitBreaker()

    out = await svc.embed_batch(["first", "second", "third"])
    assert out == [[9.0] * 4, [9.0] * 4, [9.0] * 4]
    assert embedder.doc_calls[0] == ["first", "second", "third"]
    assert embedder.doc_calls[-3:] == [["first"], ["second"], ["third"]]


# ---- 2. RateLimitMiddleware JWT verification ---------------------------------


def test_rate_limit_keys_verified_jwt_by_user_and_rejects_fake_tokens(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-rate-limit-secret-key-at-least-32b")
    rl = RateLimitMiddleware(app=None, per_min=60, burst=2)

    valid_user_1 = sessions.issue_access_token("user-111")
    valid_user_2 = sessions.issue_access_token("user-222")
    expired_user_1 = sessions.issue_access_token("user-111", now=int(time.time()) - sessions.ACCESS_TTL_S - 10)

    def _scope(auth_header: bytes | None, ip: str = "198.51.100.10", xff: bytes | None = None):
        headers = []
        if auth_header is not None:
            headers.append((b"authorization", auth_header))
        if xff is not None:
            headers.append((b"x-forwarded-for", xff))
        return {"type": "http", "path": "/api/v2/notes", "headers": headers, "client": (ip, 12345)}

    # Valid HS256 JWTs key by verified u:<user_id>
    assert rl._key(_scope(f"Bearer {valid_user_1}".encode())) == "u:user-111"
    assert rl._key(_scope(f"Bearer {valid_user_2}".encode())) == "u:user-222"

    # Fake / forged / expired / malformed Bearer tokens fall back to client IP
    assert rl._key(_scope(b"Bearer fake-rotating-token-1")) == "ip:198.51.100.10"
    assert rl._key(_scope(b"Bearer fake-rotating-token-2")) == "ip:198.51.100.10"
    assert rl._key(_scope(f"Bearer {expired_user_1}".encode())) == "ip:198.51.100.10"
    assert rl._key(_scope(b"Bearer header.payload.badsig")) == "ip:198.51.100.10"
    assert rl._key(_scope(b"Basic dXNlcjpwYXNz")) == "ip:198.51.100.10"
    assert rl._key(_scope(None, ip="10.0.0.1", xff=b"203.0.113.5, 10.0.0.1")) == "ip:203.0.113.5"


@pytest.mark.asyncio
async def test_rate_limit_cannot_bypass_by_rotating_fake_bearer_tokens(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-rate-limit-secret-key-at-least-32b")
    sent_statuses: list[int] = []

    async def ok_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def capture_send(msg):
        if msg["type"] == "http.response.start":
            sent_statuses.append(msg["status"])

    rl = RateLimitMiddleware(app=ok_app, per_min=0.001, burst=2)
    for i in range(3):
        scope = {
            "type": "http",
            "path": "/api/v2/chat",
            "headers": [(b"authorization", f"Bearer forged-{i}".encode())],
            "client": ("192.0.2.99", 5000 + i),
        }
        await rl(scope, AsyncMock(), capture_send)

    assert sent_statuses == [200, 200, 429]


# ---- 3. Google OAuth non-blocking & shared session ---------------------------


@pytest.mark.asyncio
async def test_verify_google_token_runs_in_thread_with_shared_session_and_does_not_block_loop(monkeypatch):
    monkeypatch.delenv("DEBUG", raising=False)
    seen_requests = []
    loop_ticks = 0

    def slow_blocking_verify(token, req, audience):
        seen_requests.append((token, req, audience))
        time.sleep(0.05)
        return {
            "sub": "google-sub-123",
            "email": "ada@example.com",
            "email_verified": True,
            "name": "Ada",
            "picture": "https://example.com/ada.png",
        }

    monkeypatch.setattr(google_oauth.id_token, "verify_oauth2_token", slow_blocking_verify)

    async def ticker():
        nonlocal loop_ticks
        for _ in range(4):
            await asyncio.sleep(0.005)
            loop_ticks += 1

    res1, res2, _ = await asyncio.gather(
        google_oauth.verify_google_token("tok-1"),
        google_oauth.verify_google_token("tok-2"),
        ticker(),
    )

    assert res1["google_id"] == "google-sub-123"
    assert res2["email"] == "ada@example.com"
    assert loop_ticks == 4  # event loop kept ticking while worker thread slept
    assert len(seen_requests) == 2
    assert seen_requests[0][1] is google_oauth._google_request
    assert seen_requests[1][1] is google_oauth._google_request
    assert google_oauth._google_request.session is google_oauth._http_session


# ---- 4. SpacedRepetitionService unexposed invariant --------------------------


@pytest.mark.asyncio
async def test_get_due_items_sql_excludes_null_next_review_due():
    captured_queries: list[str] = []

    class _CapturingPg:
        async def execute_query(self, query: str, params=None):
            captured_queries.append(query)
            return []

    sr = SpacedRepetitionService(_CapturingPg(), algorithm="fsrs")
    due = await sr.get_due_items("user-1", limit=10)

    assert due == []
    assert len(captured_queries) == 1
    normalized = " ".join(captured_queries[0].split())
    assert "ps.next_review_due IS NOT NULL" in normalized
    assert "ps.next_review_due <= :now" in normalized
    assert "ps.next_review_due IS NULL" not in normalized
    assert "NULLS FIRST" not in normalized
