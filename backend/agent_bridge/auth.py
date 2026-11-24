"""Agent-key authentication + simple per-key rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Optional

from backend.agent_bridge.keys import (
    AgentPrincipal,
    hashes_match,
    key_row_is_active,
    parse_key_prefix,
)
from backend.agent_bridge.repository import BridgeRepository


async def authenticate_agent_key(repo: BridgeRepository, token: Optional[str]) -> Optional[AgentPrincipal]:
    """Resolve a bearer token to a principal, or None (unknown, revoked, expired, bad hash)."""
    if not token:
        return None
    prefix = parse_key_prefix(token.strip())
    if prefix is None:
        return None
    row = await repo.get_key_by_prefix(prefix)
    if not row or not hashes_match(row["key_hash"], token.strip()):
        return None
    if not key_row_is_active(row):
        return None
    try:
        await repo.touch_key(str(row["id"]))
    except Exception:
        pass
    return AgentPrincipal(user_id=str(row["user_id"]), key_id=str(row["id"]),
                          scopes=frozenset(row.get("scopes") or []))


class SlidingWindowLimiter:
    """In-process sliding-window limiter keyed by agent key id.

    TODO(agent-bridge): move to Postgres/Redis if the backend runs >1 worker; this only
    limits per process.
    """

    def __init__(self, max_calls: int = 120, window_seconds: float = 60.0):
        self.max_calls = max_calls
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self._hits[key]
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.max_calls:
            return False
        q.append(now)
        return True
