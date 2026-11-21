"""Per-user daily quotas on LLM-backed actions, so one account can't run up the Gemini bill.

Counts live in Postgres (`usage_daily`), so they hold across restarts and API instances. The check
and the increment are one atomic upsert: two requests at the limit can't both pass.

Limits come from the environment (QUOTA_<KIND>_PER_DAY); 0 disables a kind. Defaults suit one
person studying heavily, not a bulk importer (bulk book ingestion uses scripts, not the API).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException

from backend.auth.middleware import get_current_user

DEFAULTS = {"ingest": 40, "chat": 300}


def limit_for(kind: str) -> int:
    return int(os.getenv(f"QUOTA_{kind.upper()}_PER_DAY", DEFAULTS.get(kind, 0)))


class QuotaExceeded(Exception):
    def __init__(self, kind: str, limit: int):
        self.kind, self.limit = kind, limit


async def consume(pg, user_id: str, kind: str, n: int = 1) -> int:
    """Add n to today's count (UTC) unless that would pass the limit. Returns the new count."""
    limit = limit_for(kind)
    if limit <= 0:
        return 0
    rows = await pg.execute_query(
        """
        INSERT INTO usage_daily (user_id, day, kind, count) VALUES (CAST(:u AS uuid), :d, :k, :n)
        ON CONFLICT (user_id, day, kind) DO UPDATE SET count = usage_daily.count + :n
            WHERE usage_daily.count + :n <= :lim
        RETURNING count
        """,
        {"u": user_id, "d": datetime.now(timezone.utc).date(), "k": kind, "n": n, "lim": limit},
    )
    if not rows:  # the WHERE refused the update: already at the limit
        raise QuotaExceeded(kind, limit)
    if rows[0]["count"] > limit:  # first insert of the day with n > limit
        raise QuotaExceeded(kind, limit)
    return int(rows[0]["count"])


def require_quota(kind: str):
    """FastAPI dependency: charge one unit of `kind` to the caller, or answer 429."""

    async def _dep(current_user: dict = Depends(get_current_user)) -> dict:
        from backend.db.postgres_client import get_postgres_client

        try:
            await consume(await get_postgres_client(), str(current_user["id"]), kind)
        except QuotaExceeded as e:
            raise HTTPException(status_code=429, detail=f"Daily limit reached for {e.kind} ({e.limit}/day). It resets at 00:00 UTC.",
                                headers={"Retry-After": str(_seconds_to_utc_midnight())})
        return current_user

    return _dep


def _seconds_to_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    return int((86400 - (now.hour * 3600 + now.minute * 60 + now.second)) or 1)
