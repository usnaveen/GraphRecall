"""Persistence for the agent bridge.

Every public method takes ``user_id`` first and every query filters by it. The MCP
tools and REST routes never accept a user_id from the caller: it always comes from
the authenticated principal (agent key) or the Google-authenticated user.

Two implementations share one interface:

* :class:`PostgresBridgeRepository` - production, raw SQL like the rest of the backend.
* :class:`InMemoryBridgeRepository` - tests / local demos, same semantics
  (uniqueness, ownership, atomic claim with lease).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from backend.agent_bridge.keys import generate_key

DEFAULT_LEASE_SECONDS = 15 * 60
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_REQUEST_TTL = timedelta(days=2)

FEED_STATUSES = {"pending", "approved", "rejected", "expired"}
REQUEST_TERMINAL = {"answered", "failed", "cancelled", "expired"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BridgeRepository(ABC):
    # ---- keys -----------------------------------------------------------
    @abstractmethod
    async def create_key(
        self, user_id: str, name: str, scopes: list[str], expires_at: Optional[datetime] = None
    ) -> tuple[dict, str]:
        """Returns (row without hash, full plaintext key - show once)."""

    @abstractmethod
    async def list_keys(self, user_id: str) -> list[dict]: ...

    @abstractmethod
    async def revoke_key(self, user_id: str, key_id: str) -> bool: ...

    @abstractmethod
    async def get_key_by_prefix(self, key_prefix: str) -> Optional[dict]:
        """Auth lookup only (includes key_hash). Not user-scoped by design: the prefix
        identifies the key, and the returned row carries the owning user_id."""

    @abstractmethod
    async def touch_key(self, key_id: str) -> None: ...

    # ---- feed -----------------------------------------------------------
    @abstractmethod
    async def insert_feed_item(self, user_id: str, item: dict) -> tuple[dict, bool]:
        """Insert or return existing (idempotency_key or (dedupe_key, target_date)).
        Returns (row, created)."""

    @abstractmethod
    async def list_feed_items(
        self,
        user_id: str,
        status: Optional[str] = None,
        target_date: Optional[date] = None,
        limit: int = 50,
    ) -> list[dict]: ...

    @abstractmethod
    async def set_feed_item_status(
        self, user_id: str, item_id: str, status: str
    ) -> Optional[dict]: ...

    @abstractmethod
    async def owned_feed_item_ids(self, user_id: str, item_ids: list[str]) -> set[str]: ...

    @abstractmethod
    async def upsert_digest(self, user_id: str, digest: dict) -> dict: ...

    @abstractmethod
    async def get_digest(self, user_id: str, digest_date: date) -> Optional[dict]: ...

    # ---- request queue ----------------------------------------------------
    @abstractmethod
    async def enqueue_request(
        self,
        user_id: str,
        question: str,
        context: Optional[dict] = None,
        conversation_id: Optional[str] = None,
        ttl: timedelta = DEFAULT_REQUEST_TTL,
    ) -> dict: ...

    @abstractmethod
    async def get_request(self, user_id: str, request_id: str) -> Optional[dict]: ...

    @abstractmethod
    async def list_requests(
        self, user_id: str, statuses: Optional[list[str]] = None, limit: int = 20
    ) -> list[dict]: ...

    @abstractmethod
    async def cancel_request(self, user_id: str, request_id: str) -> Optional[dict]: ...

    @abstractmethod
    async def claim_request(
        self,
        user_id: str,
        key_id: str,
        request_id: Optional[str] = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> Optional[dict]:
        """Atomically claim one claimable request (queued, or claimed with an expired
        lease). Returns the row incl. a fresh ``claim_token``, or None."""

    @abstractmethod
    async def complete_request(
        self,
        user_id: str,
        request_id: str,
        claim_token: str,
        *,
        answer_text: Optional[str] = None,
        answer_json: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> Optional[dict]:
        """Finish a claimed request. Only succeeds if ``claim_token`` matches the
        current claim and the lease has not expired."""


# ============================================================================
# Postgres
# ============================================================================

_KEY_COLS = "id, user_id, name, key_prefix, scopes, created_at, last_used_at, expires_at, revoked_at"


def _row(r: Optional[dict]) -> Optional[dict]:
    if r is None:
        return None
    out = {}
    for k, v in r.items():
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, str) and k in {"body_json", "context_json", "answer_json"}:
            try:
                v = json.loads(v)
            except ValueError:
                pass
        out[k] = v
    for k in ("item_ids",):
        if k in out and out[k] is not None:
            out[k] = [str(x) for x in out[k]]
    return out


class PostgresBridgeRepository(BridgeRepository):
    def __init__(self, pg_client: Any):
        self.pg = pg_client

    # ---- keys -----------------------------------------------------------
    async def create_key(self, user_id, name, scopes, expires_at=None):
        gen = generate_key()
        rows = await self.pg.execute_query(
            f"""
            INSERT INTO agent_api_keys (user_id, name, key_prefix, key_hash, scopes, expires_at)
            VALUES (CAST(:user_id AS UUID), :name, :key_prefix, :key_hash,
                    CAST(:scopes AS TEXT[]), :expires_at)
            RETURNING {_KEY_COLS}
            """,
            {
                "user_id": user_id,
                "name": name,
                "key_prefix": gen.key_prefix,
                "key_hash": gen.key_hash,
                "scopes": scopes,
                "expires_at": expires_at,
            },
        )
        return _row(rows[0]), gen.full_key

    async def list_keys(self, user_id):
        rows = await self.pg.execute_query(
            f"SELECT {_KEY_COLS} FROM agent_api_keys WHERE user_id = CAST(:user_id AS UUID) "
            "ORDER BY created_at DESC",
            {"user_id": user_id},
        )
        return [_row(r) for r in rows]

    async def revoke_key(self, user_id, key_id):
        rows = await self.pg.execute_query(
            """
            UPDATE agent_api_keys SET revoked_at = NOW()
            WHERE id = CAST(:key_id AS UUID) AND user_id = CAST(:user_id AS UUID)
              AND revoked_at IS NULL
            RETURNING id
            """,
            {"key_id": key_id, "user_id": user_id},
        )
        return bool(rows)

    async def get_key_by_prefix(self, key_prefix):
        rows = await self.pg.execute_query(
            f"SELECT {_KEY_COLS}, key_hash FROM agent_api_keys WHERE key_prefix = :p LIMIT 1",
            {"p": key_prefix},
        )
        return _row(rows[0]) if rows else None

    async def touch_key(self, key_id):
        # Throttled so every MCP call does not write.
        await self.pg.execute_update(
            """
            UPDATE agent_api_keys SET last_used_at = NOW()
            WHERE id = CAST(:id AS UUID)
              AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '5 minutes')
            """,
            {"id": key_id},
        )

    # ---- feed -----------------------------------------------------------
    async def insert_feed_item(self, user_id, item):
        params = {
            "user_id": user_id,
            "key_id": item.get("key_id"),
            "item_kind": item["item_kind"],
            "title": item["title"],
            "summary": item["summary"],
            "body_json": json.dumps(item.get("body_json") or {}),
            "source_url": item.get("source_url"),
            "source_kind": item["source_kind"],
            "reason": item["reason"],
            "concept_ids": item.get("concept_ids") or [],
            "target_date": item["target_date"],
            "dedupe_key": item["dedupe_key"],
            "idempotency_key": item.get("idempotency_key"),
        }
        rows = await self.pg.execute_query(
            """
            INSERT INTO agent_feed_items (
                user_id, key_id, status, item_kind, title, summary, body_json, source_url,
                source_kind, reason, concept_ids, target_date, dedupe_key, idempotency_key)
            VALUES (
                CAST(:user_id AS UUID), CAST(:key_id AS UUID), 'pending', :item_kind, :title,
                :summary, CAST(:body_json AS JSONB), :source_url, :source_kind, :reason,
                CAST(:concept_ids AS TEXT[]), :target_date, :dedupe_key,
                CAST(:idempotency_key AS VARCHAR))
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            params,
        )
        if rows:
            return _row(rows[0]), True
        existing = await self.pg.execute_query(
            """
            SELECT * FROM agent_feed_items
            WHERE user_id = CAST(:user_id AS UUID)
              AND ((CAST(:idempotency_key AS VARCHAR) IS NOT NULL
                    AND idempotency_key = CAST(:idempotency_key AS VARCHAR))
                   OR (dedupe_key = :dedupe_key AND target_date = :target_date))
            ORDER BY created_at ASC
            LIMIT 1
            """,
            params,
        )
        if not existing:  # pragma: no cover - would mean a conflict on another user's row
            raise RuntimeError("Feed item conflict but no owned row found")
        return _row(existing[0]), False

    async def list_feed_items(self, user_id, status=None, target_date=None, limit=50):
        rows = await self.pg.execute_query(
            """
            SELECT * FROM agent_feed_items
            WHERE user_id = CAST(:user_id AS UUID)
              AND (CAST(:status AS VARCHAR) IS NULL OR status = CAST(:status AS VARCHAR))
              AND (CAST(:target_date AS DATE) IS NULL OR target_date = CAST(:target_date AS DATE))
            ORDER BY target_date DESC, created_at DESC
            LIMIT :limit
            """,
            {"user_id": user_id, "status": status, "target_date": target_date, "limit": limit},
        )
        return [_row(r) for r in rows]

    async def set_feed_item_status(self, user_id, item_id, status):
        if status not in FEED_STATUSES:
            raise ValueError(f"invalid status {status}")
        rows = await self.pg.execute_query(
            """
            UPDATE agent_feed_items SET status = :status, reviewed_at = NOW()
            WHERE id = CAST(:id AS UUID) AND user_id = CAST(:user_id AS UUID)
            RETURNING *
            """,
            {"id": item_id, "user_id": user_id, "status": status},
        )
        return _row(rows[0]) if rows else None

    async def owned_feed_item_ids(self, user_id, item_ids):
        if not item_ids:
            return set()
        rows = await self.pg.execute_query(
            """
            SELECT id FROM agent_feed_items
            WHERE user_id = CAST(:user_id AS UUID) AND id = ANY(CAST(:ids AS UUID[]))
            """,
            {"user_id": user_id, "ids": item_ids},
        )
        return {str(r["id"]) for r in rows}

    async def upsert_digest(self, user_id, digest):
        rows = await self.pg.execute_query(
            """
            INSERT INTO agent_daily_digests
                (user_id, key_id, digest_date, title, summary, item_ids, focus_concept_ids)
            VALUES (CAST(:user_id AS UUID), CAST(:key_id AS UUID), :digest_date, :title,
                    :summary, CAST(:item_ids AS UUID[]), CAST(:focus AS TEXT[]))
            ON CONFLICT (user_id, digest_date) DO UPDATE SET
                key_id = EXCLUDED.key_id, title = EXCLUDED.title, summary = EXCLUDED.summary,
                item_ids = EXCLUDED.item_ids, focus_concept_ids = EXCLUDED.focus_concept_ids,
                updated_at = NOW()
            RETURNING *
            """,
            {
                "user_id": user_id,
                "key_id": digest.get("key_id"),
                "digest_date": digest["digest_date"],
                "title": digest["title"],
                "summary": digest.get("summary", ""),
                "item_ids": digest.get("item_ids") or [],
                "focus": digest.get("focus_concept_ids") or [],
            },
        )
        return _row(rows[0])

    async def get_digest(self, user_id, digest_date):
        rows = await self.pg.execute_query(
            "SELECT * FROM agent_daily_digests WHERE user_id = CAST(:user_id AS UUID) "
            "AND digest_date = :d",
            {"user_id": user_id, "d": digest_date},
        )
        return _row(rows[0]) if rows else None

    # ---- request queue ----------------------------------------------------
    async def enqueue_request(self, user_id, question, context=None, conversation_id=None,
                              ttl=DEFAULT_REQUEST_TTL):
        rows = await self.pg.execute_query(
            """
            INSERT INTO agent_requests (user_id, conversation_id, question, context_json, expires_at)
            VALUES (CAST(:user_id AS UUID), CAST(:conversation_id AS UUID), :question,
                    CAST(:context AS JSONB), :expires_at)
            RETURNING *
            """,
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "question": question,
                "context": json.dumps(context or {}),
                "expires_at": _now() + ttl,
            },
        )
        return _row(rows[0])

    async def get_request(self, user_id, request_id):
        rows = await self.pg.execute_query(
            "SELECT * FROM agent_requests WHERE id = CAST(:id AS UUID) "
            "AND user_id = CAST(:user_id AS UUID)",
            {"id": request_id, "user_id": user_id},
        )
        return _row(rows[0]) if rows else None

    async def list_requests(self, user_id, statuses=None, limit=20):
        rows = await self.pg.execute_query(
            """
            SELECT * FROM agent_requests
            WHERE user_id = CAST(:user_id AS UUID)
              AND (CAST(:statuses AS TEXT[]) IS NULL OR status = ANY(CAST(:statuses AS TEXT[])))
              AND (expires_at IS NULL OR expires_at > NOW() OR status IN ('answered','failed'))
            ORDER BY created_at ASC
            LIMIT :limit
            """,
            {"user_id": user_id, "statuses": statuses, "limit": limit},
        )
        return [_row(r) for r in rows]

    async def cancel_request(self, user_id, request_id):
        rows = await self.pg.execute_query(
            """
            UPDATE agent_requests SET status = 'cancelled', claim_token = NULL
            WHERE id = CAST(:id AS UUID) AND user_id = CAST(:user_id AS UUID)
              AND status IN ('queued', 'claimed')
            RETURNING *
            """,
            {"id": request_id, "user_id": user_id},
        )
        return _row(rows[0]) if rows else None

    async def claim_request(self, user_id, key_id, request_id=None,
                            lease_seconds=DEFAULT_LEASE_SECONDS, max_attempts=DEFAULT_MAX_ATTEMPTS):
        # Single statement: the sub-select locks the candidate row with
        # FOR UPDATE SKIP LOCKED, so two concurrent claimers can never both win.
        rows = await self.pg.execute_query(
            """
            UPDATE agent_requests r SET
                status = 'claimed',
                claimed_by_key_id = CAST(:key_id AS UUID),
                claim_token = CAST(:token AS UUID),
                claimed_at = NOW(),
                lease_expires_at = NOW() + make_interval(secs => :lease),
                attempts = r.attempts + 1
            WHERE r.id = (
                SELECT id FROM agent_requests
                WHERE user_id = CAST(:user_id AS UUID)
                  AND (CAST(:request_id AS UUID) IS NULL OR id = CAST(:request_id AS UUID))
                  AND (status = 'queued' OR (status = 'claimed' AND lease_expires_at < NOW()))
                  AND attempts < :max_attempts
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING r.*
            """,
            {
                "user_id": user_id,
                "key_id": key_id,
                "token": str(uuid.uuid4()),
                "lease": float(lease_seconds),
                "request_id": request_id,
                "max_attempts": max_attempts,
            },
        )
        return _row(rows[0]) if rows else None

    async def complete_request(self, user_id, request_id, claim_token, *, answer_text=None,
                               answer_json=None, error=None):
        status = "failed" if error else "answered"
        rows = await self.pg.execute_query(
            """
            UPDATE agent_requests SET
                status = :status, answer_text = :answer_text,
                answer_json = CAST(:answer_json AS JSONB), error = :error,
                answered_at = NOW(), lease_expires_at = NULL
            WHERE id = CAST(:id AS UUID) AND user_id = CAST(:user_id AS UUID)
              AND status = 'claimed' AND claim_token = CAST(:token AS UUID)
              AND lease_expires_at > NOW()
            RETURNING *
            """,
            {
                "status": status,
                "answer_text": answer_text,
                "answer_json": json.dumps(answer_json) if answer_json is not None else None,
                "error": error,
                "id": request_id,
                "user_id": user_id,
                "token": claim_token,
            },
        )
        return _row(rows[0]) if rows else None


# ============================================================================
# In-memory (tests / demos)
# ============================================================================


class InMemoryBridgeRepository(BridgeRepository):
    def __init__(self) -> None:
        self.keys: dict[str, dict] = {}
        self.feed: dict[str, dict] = {}
        self.digests: dict[tuple[str, date], dict] = {}
        self.requests: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _public_key(row: dict) -> dict:
        return {k: v for k, v in row.items() if k != "key_hash"}

    async def create_key(self, user_id, name, scopes, expires_at=None):
        gen = generate_key()
        row = {
            "id": str(uuid.uuid4()), "user_id": user_id, "name": name,
            "key_prefix": gen.key_prefix, "key_hash": gen.key_hash, "scopes": list(scopes),
            "created_at": _now(), "last_used_at": None, "expires_at": expires_at,
            "revoked_at": None,
        }
        self.keys[row["id"]] = row
        return self._public_key(row), gen.full_key

    async def list_keys(self, user_id):
        return [self._public_key(r) for r in self.keys.values() if r["user_id"] == user_id]

    async def revoke_key(self, user_id, key_id):
        row = self.keys.get(key_id)
        if not row or row["user_id"] != user_id or row["revoked_at"]:
            return False
        row["revoked_at"] = _now()
        return True

    async def get_key_by_prefix(self, key_prefix):
        for r in self.keys.values():
            if r["key_prefix"] == key_prefix:
                return dict(r)
        return None

    async def touch_key(self, key_id):
        if key_id in self.keys:
            self.keys[key_id]["last_used_at"] = _now()

    async def insert_feed_item(self, user_id, item):
        async with self._lock:
            for r in self.feed.values():
                if r["user_id"] != user_id:
                    continue
                if item.get("idempotency_key") and r.get("idempotency_key") == item["idempotency_key"]:
                    return dict(r), False
                if r["dedupe_key"] == item["dedupe_key"] and r["target_date"] == item["target_date"]:
                    return dict(r), False
            row = {
                "id": str(uuid.uuid4()), "user_id": user_id, "status": "pending",
                "created_at": _now(), "reviewed_at": None,
                "body_json": item.get("body_json") or {}, "concept_ids": item.get("concept_ids") or [],
                **{k: item.get(k) for k in (
                    "key_id", "item_kind", "title", "summary", "source_url", "source_kind",
                    "reason", "target_date", "dedupe_key", "idempotency_key")},
            }
            self.feed[row["id"]] = row
            return dict(row), True

    async def list_feed_items(self, user_id, status=None, target_date=None, limit=50):
        rows = [
            dict(r) for r in self.feed.values()
            if r["user_id"] == user_id
            and (status is None or r["status"] == status)
            and (target_date is None or r["target_date"] == target_date)
        ]
        rows.sort(key=lambda r: (r["target_date"], r["created_at"]), reverse=True)
        return rows[:limit]

    async def set_feed_item_status(self, user_id, item_id, status):
        if status not in FEED_STATUSES:
            raise ValueError(f"invalid status {status}")
        r = self.feed.get(item_id)
        if not r or r["user_id"] != user_id:
            return None
        r["status"] = status
        r["reviewed_at"] = _now()
        return dict(r)

    async def owned_feed_item_ids(self, user_id, item_ids):
        return {i for i in item_ids if i in self.feed and self.feed[i]["user_id"] == user_id}

    async def upsert_digest(self, user_id, digest):
        k = (user_id, digest["digest_date"])
        existing = self.digests.get(k)
        row = {
            "id": existing["id"] if existing else str(uuid.uuid4()),
            "user_id": user_id,
            "key_id": digest.get("key_id"),
            "digest_date": digest["digest_date"],
            "title": digest["title"],
            "summary": digest.get("summary", ""),
            "item_ids": list(digest.get("item_ids") or []),
            "focus_concept_ids": list(digest.get("focus_concept_ids") or []),
            "updated_at": _now(),
        }
        self.digests[k] = row
        return dict(row)

    async def get_digest(self, user_id, digest_date):
        r = self.digests.get((user_id, digest_date))
        return dict(r) if r else None

    async def enqueue_request(self, user_id, question, context=None, conversation_id=None,
                              ttl=DEFAULT_REQUEST_TTL):
        row = {
            "id": str(uuid.uuid4()), "user_id": user_id, "conversation_id": conversation_id,
            "question": question, "context_json": context or {}, "status": "queued",
            "claimed_by_key_id": None, "claim_token": None, "lease_expires_at": None,
            "attempts": 0, "answer_text": None, "answer_json": None, "error": None,
            "created_at": _now(), "claimed_at": None, "answered_at": None,
            "expires_at": _now() + ttl,
        }
        self.requests[row["id"]] = row
        return dict(row)

    async def get_request(self, user_id, request_id):
        r = self.requests.get(request_id)
        return dict(r) if r and r["user_id"] == user_id else None

    async def list_requests(self, user_id, statuses=None, limit=20):
        now = _now()
        rows = [
            dict(r) for r in self.requests.values()
            if r["user_id"] == user_id
            and (statuses is None or r["status"] in statuses)
            and (r["expires_at"] is None or r["expires_at"] > now
                 or r["status"] in ("answered", "failed"))
        ]
        rows.sort(key=lambda r: r["created_at"])
        return rows[:limit]

    async def cancel_request(self, user_id, request_id):
        async with self._lock:
            r = self.requests.get(request_id)
            if not r or r["user_id"] != user_id or r["status"] not in ("queued", "claimed"):
                return None
            r["status"] = "cancelled"
            r["claim_token"] = None
            return dict(r)

    async def claim_request(self, user_id, key_id, request_id=None,
                            lease_seconds=DEFAULT_LEASE_SECONDS, max_attempts=DEFAULT_MAX_ATTEMPTS):
        async with self._lock:
            now = _now()
            candidates = sorted(
                (
                    r for r in self.requests.values()
                    if r["user_id"] == user_id
                    and (request_id is None or r["id"] == request_id)
                    and (r["status"] == "queued"
                         or (r["status"] == "claimed" and r["lease_expires_at"] < now))
                    and r["attempts"] < max_attempts
                    and (r["expires_at"] is None or r["expires_at"] > now)
                ),
                key=lambda r: r["created_at"],
            )
            if not candidates:
                return None
            r = candidates[0]
            r.update(
                status="claimed", claimed_by_key_id=key_id, claim_token=str(uuid.uuid4()),
                claimed_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds),
                attempts=r["attempts"] + 1,
            )
            return dict(r)

    async def complete_request(self, user_id, request_id, claim_token, *, answer_text=None,
                               answer_json=None, error=None):
        async with self._lock:
            r = self.requests.get(request_id)
            if (
                not r or r["user_id"] != user_id or r["status"] != "claimed"
                or r["claim_token"] != claim_token or r["lease_expires_at"] <= _now()
            ):
                return None
            r.update(
                status="failed" if error else "answered", answer_text=answer_text,
                answer_json=answer_json, error=error, answered_at=_now(), lease_expires_at=None,
            )
            return dict(r)
