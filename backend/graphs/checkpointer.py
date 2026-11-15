"""
LangGraph checkpointer configuration.

Why this exists: every graph is compiled at import time (module-level
``*_graph = create_*_graph()``), but a Postgres-backed saver needs an open
async connection, which only exists once the event loop is running. The
previous version returned ``AsyncPostgresSaver.from_conn_string(...)`` — an
async *context manager*, not a saver — and only in ``ENVIRONMENT=production``,
so in practice every graph ran on ``MemorySaver`` and a paused HITL ingestion
(``interrupt()`` in ingestion_graph.user_review) was lost on API restart.

Now:
- ``get_checkpointer()`` returns one shared ``AsyncPostgresSaver`` built on a
  psycopg ``AsyncConnectionPool`` created *closed* (``open=False``), so graphs
  can be compiled against it at import time.
- ``open_checkpointer()`` (FastAPI lifespan startup) opens the pool and runs
  ``setup()`` to create the checkpoint tables; ``close_checkpointer()`` closes it.
- ``CHECKPOINTER=memory|postgres|auto`` overrides the choice. ``auto`` (default)
  uses Postgres when ``DATABASE_URL`` is set, except under pytest.

Thread ids are UUIDs everywhere (chat conversation ids, ingestion runs), so one
shared checkpoint table is safe across graphs.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

_saver: Optional[Any] = None
_pool: Optional[Any] = None
_postgres_ready = False
_open_lock: Optional[asyncio.Lock] = None


def _psycopg_conninfo(url: str) -> str:
    """SQLAlchemy-style URLs (postgresql+asyncpg://) → plain libpq URL."""
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _wants_postgres(use_postgres: bool) -> bool:
    mode = os.getenv("CHECKPOINTER", "auto").strip().lower()
    if mode == "memory":
        return False
    if not os.getenv("DATABASE_URL"):
        return False
    if mode == "postgres" or use_postgres:
        return True
    return "pytest" not in sys.modules


def _memory_saver():
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


def _deferred_postgres_saver(pool):
    """AsyncPostgresSaver that binds its event loop at startup, not construction.

    AsyncPostgresSaver.__init__ calls asyncio.get_running_loop() (used only by its
    sync wrappers), which raises when graphs are compiled at import time. Every
    other attribute is set before that call, so we finish construction ourselves
    and bind the loop in open_checkpointer(). test_checkpointer_persistence.py
    fails if a library upgrade changes this.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    class DeferredAsyncPostgresSaver(AsyncPostgresSaver):
        def __init__(self, conn):
            try:
                super().__init__(conn)
            except RuntimeError:  # no running event loop yet
                from psycopg import Capabilities

                self.loop = None
                self.supports_pipeline = Capabilities().has_pipeline()

        def bind_loop(self) -> None:
            self.loop = asyncio.get_running_loop()

        # Self-opening: callers outside the FastAPI lifespan (backend/scripts/
        # seed_content.py, scripts/ingest_book.py, notebooks) just work.
        async def aget_tuple(self, config):
            await open_checkpointer()
            return await super().aget_tuple(config)

        async def alist(self, *args, **kwargs):
            await open_checkpointer()
            async for item in super().alist(*args, **kwargs):
                yield item

        async def aput(self, *args, **kwargs):
            await open_checkpointer()
            return await super().aput(*args, **kwargs)

        async def aput_writes(self, *args, **kwargs):
            await open_checkpointer()
            return await super().aput_writes(*args, **kwargs)

        async def adelete_thread(self, thread_id):
            await open_checkpointer()
            return await super().adelete_thread(thread_id)

    return DeferredAsyncPostgresSaver(pool)


def get_checkpointer(use_postgres: bool = False):
    """Return the process-wide checkpointer (Postgres if configured, else memory).

    Safe to call at import time: the Postgres pool is created closed and is
    opened by ``open_checkpointer()`` during app startup.
    """
    global _saver, _pool
    if _saver is not None:
        return _saver

    if _wants_postgres(use_postgres):
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool

            _pool = AsyncConnectionPool(
                conninfo=_psycopg_conninfo(os.environ["DATABASE_URL"]),
                min_size=1,
                max_size=int(os.getenv("CHECKPOINTER_POOL_MAX", "5")),
                open=False,
                # Settings AsyncPostgresSaver requires (see its docs).
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            )
            _saver = _deferred_postgres_saver(_pool)
            logger.info("checkpointer: AsyncPostgresSaver configured (pool opens at startup)")
            return _saver
        except ImportError as e:
            logger.warning(
                "checkpointer: postgres checkpointer deps missing, using MemorySaver",
                error=str(e),
            )

    _saver = _memory_saver()
    logger.info("checkpointer: using MemorySaver (state is lost on restart)")
    return _saver


async def open_checkpointer() -> str:
    """Open the pool and create checkpoint tables. Call from app lifespan startup.

    Returns the active backend name. If Postgres can't be reached the graphs keep
    their compiled saver and requests that need it will fail loudly, rather than
    silently losing HITL state.
    """
    global _postgres_ready, _open_lock
    saver = get_checkpointer()
    if _pool is None:
        return "memory"
    if _postgres_ready:
        return "postgres"
    if _open_lock is None:
        _open_lock = asyncio.Lock()
    async with _open_lock:
        if not _postgres_ready:
            saver.bind_loop()
            await _pool.open(wait=True, timeout=float(os.getenv("CHECKPOINTER_CONNECT_TIMEOUT", "15")))
            await saver.setup()
            _postgres_ready = True
            logger.info("checkpointer: Postgres checkpoint tables ready")
    return "postgres"


async def close_checkpointer() -> None:
    global _postgres_ready, _open_lock
    if _pool is not None and _postgres_ready:
        await _pool.close()
    _postgres_ready = False
    _open_lock = None


def checkpointer_status() -> dict:
    """For /health: which backend is active and whether it is usable."""
    if _saver is None:
        return {"backend": "unset", "ready": False}
    if _pool is None:
        return {"backend": "memory", "ready": True, "durable": False}
    return {"backend": "postgres", "ready": _postgres_ready, "durable": True}


async def setup_postgres_checkpointer() -> Optional[object]:
    """Backward-compatible alias for older callers."""
    backend = await open_checkpointer()
    return get_checkpointer() if backend == "postgres" else None
