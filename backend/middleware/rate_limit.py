"""Token-bucket request rate limiting per client (bearer token, else IP).

In-memory, so it bounds bursts per API instance; daily cost limits live in Postgres
(backend/services/quota.py). Defaults: RATE_LIMIT_PER_MIN=120 requests, burst RATE_LIMIT_BURST=40.
Health checks are exempt. Answers 429 with Retry-After.
"""

from __future__ import annotations

import hashlib
import os
import time

EXEMPT = ("/api/v2/health", "/health", "/docs", "/openapi.json")


class RateLimitMiddleware:
    def __init__(self, app, per_min: float | None = None, burst: float | None = None, max_clients: int = 50_000):
        self.app = app
        self.rate = float(per_min or os.getenv("RATE_LIMIT_PER_MIN", 120)) / 60.0
        self.burst = float(burst or os.getenv("RATE_LIMIT_BURST", 40))
        self.max_clients = max_clients
        self.buckets: dict[str, tuple[float, float]] = {}

    def _key(self, scope) -> str:
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"")
        if auth:
            return "t:" + hashlib.sha256(auth).hexdigest()[:24]
        fwd = headers.get(b"x-forwarded-for", b"").split(b",")[0].strip()
        client = scope.get("client") or ("?", 0)
        return "ip:" + (fwd.decode() if fwd else str(client[0]))

    def allow(self, key: str, now: float | None = None) -> tuple[bool, float]:
        now = time.monotonic() if now is None else now
        tokens, last = self.buckets.get(key, (self.burst, now))
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        if tokens < 1:
            self.buckets[key] = (tokens, now)
            return False, (1 - tokens) / self.rate
        self.buckets[key] = (tokens - 1, now)
        if len(self.buckets) > self.max_clients:  # drop the oldest half; bounded memory
            for k in sorted(self.buckets, key=lambda k: self.buckets[k][1])[: self.max_clients // 2]:
                del self.buckets[k]
        return True, 0.0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").startswith(EXEMPT) or self.rate <= 0:
            return await self.app(scope, receive, send)
        ok, retry = self.allow(self._key(scope))
        if ok:
            return await self.app(scope, receive, send)
        body = b'{"detail":"Too many requests. Slow down and retry shortly."}'
        await send({"type": "http.response.start", "status": 429,
                    "headers": [(b"content-type", b"application/json"), (b"retry-after", str(max(1, int(retry + 0.999))).encode())]})
        await send({"type": "http.response.body", "body": body})
