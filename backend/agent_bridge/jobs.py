"""Periodic maintenance for the agent bridge.

``sweep_stale_requests`` moves every user's stale questions to terminal states
(``expired`` past the deadline, ``failed`` once attempts are exhausted). The same sweep
also runs lazily, scoped to one user, whenever requests are read, listed or claimed, so
correctness does not depend on this job; it only keeps rows tidy for users who stop
polling.

TODO(agent-bridge): schedule this. GraphRecall has no job runner today. Options: a Render
Cron Job running ``python -m backend.agent_bridge.jobs`` every 10 minutes, or an
``asyncio`` loop started in ``main.lifespan`` when ``AGENT_BRIDGE_ENABLED=1``. Also expire
stale ``pending`` feed items (target_date < today - 7) there.
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.agent_bridge.repository import (
    DEFAULT_MAX_ATTEMPTS,
    BridgeRepository,
    PostgresBridgeRepository,
)


async def sweep_stale_requests(repo: BridgeRepository,
                               max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> dict[str, Any]:
    return await repo.sweep_requests(None, max_attempts=max_attempts)


async def _main() -> None:  # pragma: no cover - manual/cron entrypoint
    from backend.db.postgres_client import close_postgres_client, get_postgres_client

    pg = await get_postgres_client()
    try:
        print(await sweep_stale_requests(PostgresBridgeRepository(pg)))
    finally:
        await close_postgres_client()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
