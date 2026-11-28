"""MCP Tasks (extension ``io.modelcontextprotocol/tasks``, 2026-07-28) for the agent bridge.

A long-running tool starts a background job and returns at once. The job's state lives in
``agent_tasks`` (Postgres) so a later ``tasks/get`` finds it on any connection, even after the
client reconnects; the work itself runs as an asyncio task in this API process.

Rules encoded here (from the extension spec and Claude Code's server-author notes):
- The row is written before the answer is sent ("durably created").
- Ids are unguessable (``secrets.token_urlsafe``) and every read is bound to the owning user, so an
  unknown, expired or someone else's id all look the same: JSON-RPC -32602.
- ``failed`` is only for JSON-RPC-level errors; a job that ran but couldn't do everything is
  ``completed`` with the per-item outcomes (and ``isError`` when nothing worked) in ``result``.
- Results are kept at least 24 h; ``ttlMs`` = longest run + retention.
- A process restart orphans running jobs; a ``working`` row with no progress for longer than the
  longest run is reported ``failed`` ("interrupted") on read.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

import structlog

logger = structlog.get_logger()

EXTENSION_ID = "io.modelcontextprotocol/tasks"
MAX_RUN = timedelta(minutes=30)
RETAIN = timedelta(hours=24)
TTL_MS = int((MAX_RUN + RETAIN).total_seconds() * 1000)
POLL_MS = 5000
MAX_ACTIVE_PER_USER = 2
TERMINAL = {"completed", "failed", "cancelled"}

Progress = Callable[[str], Awaitable[None]]
Work = Callable[[Progress], Awaitable[dict]]  # returns a CallToolResult-shaped dict


class TaskNotFound(Exception):
    """Unknown, expired, or owned by another user (-32602)."""


class TooManyTasks(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def new_task_id() -> str:
    return "grt_" + secrets.token_urlsafe(24)  # 36 printable ASCII chars, no spaces (Claude Code: <=128)


class TaskStore(ABC):
    @abstractmethod
    async def create(self, task_id: str, user_id: str, key_id: Optional[str], tool: str,
                     status_message: Optional[str]) -> dict: ...

    @abstractmethod
    async def get(self, user_id: str, task_id: str) -> Optional[dict]: ...

    @abstractmethod
    async def update(self, task_id: str, *, status: Optional[str] = None, status_message: Optional[str] = None,
                     result: Optional[dict] = None, error: Optional[dict] = None) -> None: ...

    @abstractmethod
    async def request_cancel(self, user_id: str, task_id: str) -> bool: ...

    @abstractmethod
    async def count_active(self, user_id: str) -> int: ...


class PostgresTaskStore(TaskStore):
    def __init__(self, pg: Any):
        self.pg = pg

    async def create(self, task_id, user_id, key_id, tool, status_message):
        rows = await self.pg.execute_query(
            """
            INSERT INTO agent_tasks (id, user_id, key_id, tool, status, status_message, expires_at)
            VALUES (:id, CAST(:user_id AS UUID), CAST(:key_id AS UUID), :tool, 'working', :msg, :expires_at)
            RETURNING *
            """,
            {"id": task_id, "user_id": user_id, "key_id": key_id, "tool": tool, "msg": status_message,
             "expires_at": _now() + MAX_RUN + RETAIN})
        return dict(rows[0])

    async def get(self, user_id, task_id):
        rows = await self.pg.execute_query(
            "SELECT * FROM agent_tasks WHERE id = :id AND user_id = CAST(:user_id AS UUID)",
            {"id": task_id, "user_id": user_id})
        return dict(rows[0]) if rows else None

    async def update(self, task_id, *, status=None, status_message=None, result=None, error=None):
        sets, params = ["updated_at = NOW()"], {"id": task_id}
        if status is not None:
            sets.append("status = :status")
            params["status"] = status
        if status_message is not None:
            sets.append("status_message = :msg")
            params["msg"] = status_message
        if result is not None:
            sets.append("result = CAST(:result AS JSONB)")
            params["result"] = json.dumps(result)
        if error is not None:
            sets.append("error = CAST(:error AS JSONB)")
            params["error"] = json.dumps(error)
        # Never move a finished task back to working (a late progress write after cancel/finish).
        await self.pg.execute_update(
            f"UPDATE agent_tasks SET {', '.join(sets)} WHERE id = :id AND status = 'working'", params)

    async def request_cancel(self, user_id, task_id):
        rows = await self.pg.execute_query(
            "UPDATE agent_tasks SET cancel_requested = TRUE, updated_at = NOW() "
            "WHERE id = :id AND user_id = CAST(:user_id AS UUID) RETURNING id",
            {"id": task_id, "user_id": user_id})
        return bool(rows)

    async def count_active(self, user_id):
        rows = await self.pg.execute_query(
            "SELECT count(*) AS n FROM agent_tasks WHERE user_id = CAST(:user_id AS UUID) "
            "AND status = 'working' AND updated_at > :since AND expires_at > :now",
            {"user_id": user_id, "since": _now() - MAX_RUN, "now": _now()})
        return int(rows[0]["n"]) if rows else 0


class InMemoryTaskStore(TaskStore):
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def create(self, task_id, user_id, key_id, tool, status_message):
        now = _now()
        self.rows[task_id] = {"id": task_id, "user_id": user_id, "key_id": key_id, "tool": tool,
                              "status": "working", "status_message": status_message, "result": None,
                              "error": None, "cancel_requested": False, "created_at": now, "updated_at": now,
                              "expires_at": now + MAX_RUN + RETAIN}
        return dict(self.rows[task_id])

    async def get(self, user_id, task_id):
        r = self.rows.get(task_id)
        return dict(r) if r and r["user_id"] == user_id else None

    async def update(self, task_id, *, status=None, status_message=None, result=None, error=None):
        r = self.rows.get(task_id)
        if not r or r["status"] != "working":
            return
        for k, v in (("status", status), ("status_message", status_message), ("result", result), ("error", error)):
            if v is not None:
                r[k] = v
        r["updated_at"] = _now()

    async def request_cancel(self, user_id, task_id):
        r = self.rows.get(task_id)
        if not r or r["user_id"] != user_id:
            return False
        r["cancel_requested"] = True
        return True

    async def count_active(self, user_id):
        now = _now()
        return sum(1 for r in self.rows.values() if r["user_id"] == user_id and r["status"] == "working"
                   and r["updated_at"] > now - MAX_RUN and r["expires_at"] > now)


# Strong references to running jobs (an un-referenced asyncio task can be garbage collected).
_JOBS: dict[str, asyncio.Task] = {}


def tool_result(payload: dict, *, is_error: bool = False) -> dict:
    """A CallToolResult-shaped dict: the JSON payload as text, plus structuredContent."""
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}],
            "structuredContent": payload, "isError": is_error}


async def start(store: TaskStore, *, user_id: str, key_id: Optional[str], tool: str, work: Work,
                first_message: str) -> dict:
    """Write the task row, then start the job. Returns the row (before any work has run)."""
    if await store.count_active(user_id) >= MAX_ACTIVE_PER_USER:
        raise TooManyTasks(f"{MAX_ACTIVE_PER_USER} imports are already running; wait for one to finish")
    task_id = new_task_id()
    row = await store.create(task_id, user_id, key_id, tool, first_message)

    async def progress(msg: str) -> None:
        try:
            await store.update(task_id, status_message=msg[:500])
        except Exception as e:  # progress is best effort
            logger.warning("agent_tasks: progress write failed", task_id=task_id, error=str(e))

    async def run() -> None:
        try:
            result = await asyncio.wait_for(work(progress), timeout=MAX_RUN.total_seconds())
            await store.update(task_id, status="completed", result=result,
                               status_message="Finished" if not result.get("isError") else "Finished with errors")
        except asyncio.CancelledError:
            await store.update(task_id, status="cancelled", status_message="Cancelled")
            raise
        except asyncio.TimeoutError:
            await store.update(task_id, status="failed", status_message="Timed out",
                               error={"code": -32603, "message": f"Timed out after {int(MAX_RUN.total_seconds() // 60)} minutes"})
        except Exception as e:
            logger.error("agent_tasks: job failed", task_id=task_id, tool=tool, error=str(e))
            await store.update(task_id, status="failed", status_message="Failed",
                               error={"code": -32603, "message": "Internal error while importing"})
        finally:
            _JOBS.pop(task_id, None)

    _JOBS[task_id] = asyncio.create_task(run(), name=f"agent-task-{task_id}")
    return row


async def cancel(store: TaskStore, user_id: str, task_id: str) -> None:
    """Cooperative: flag the row and cancel the job if it runs in this process."""
    row = await store.get(user_id, task_id)
    if row is None or _expired(row):
        raise TaskNotFound(task_id)
    if row["status"] in TERMINAL:
        return
    await store.request_cancel(user_id, task_id)
    job = _JOBS.get(task_id)
    if job is not None:
        job.cancel()
    # Mark it now: a job cancelled before it first ran never reaches its own handler, and an orphaned
    # one (restart) has nothing running. A finish that races this is ignored (status is no longer working).
    await store.update(task_id, status="cancelled", status_message="Cancelled")


def _expired(row: dict) -> bool:
    exp = row.get("expires_at")
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp is not None and exp <= _now()


def _stale(row: dict) -> bool:
    upd = row.get("updated_at")
    if upd is None or row.get("status") != "working" or row.get("id") in _JOBS:
        return False
    if upd.tzinfo is None:
        upd = upd.replace(tzinfo=timezone.utc)
    return _now() - upd > MAX_RUN


async def get(store: TaskStore, user_id: str, task_id: str) -> dict:
    row = await store.get(user_id, task_id)
    if row is None or _expired(row):
        raise TaskNotFound(task_id)
    if _stale(row):
        await store.update(task_id, status="failed", status_message="Interrupted",
                           error={"code": -32603, "message": "The import was interrupted (server restarted)"})
        row = await store.get(user_id, task_id) or row
    return row


def wire(row: dict, *, result_type: str) -> dict:
    """The Task object (CreateTaskResult when result_type='task', GetTaskResult when 'complete')."""
    out: dict[str, Any] = {"resultType": result_type, "taskId": row["id"], "status": row["status"],
                           "createdAt": _iso(row["created_at"]), "lastUpdatedAt": _iso(row["updated_at"]),
                           "ttlMs": TTL_MS, "pollIntervalMs": POLL_MS}
    if row.get("status_message"):
        out["statusMessage"] = row["status_message"]
    if result_type == "complete":
        if row["status"] == "completed":
            out["result"] = _json(row.get("result")) or tool_result({})
        elif row["status"] == "failed":
            out["error"] = _json(row.get("error")) or {"code": -32603, "message": "Task failed"}
    return out


def status_view(row: dict) -> dict:
    """For clients without the extension: the same state, as a plain tool payload."""
    out = {"task_id": row["id"], "status": row["status"], "message": row.get("status_message"),
           "created_at": _iso(row["created_at"]), "updated_at": _iso(row["updated_at"])}
    if row["status"] == "completed":
        res = _json(row.get("result")) or {}
        out["result"] = res.get("structuredContent", res)
    elif row["status"] == "failed":
        out["error"] = (_json(row.get("error")) or {}).get("message")
    return out


def _json(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v
