"""Agent bridge against a real Postgres (migration 026, ON CONFLICT dedupe, atomic claim).

Skipped unless AGENT_BRIDGE_TEST_DATABASE_URL points at a THROWAWAY database, e.g.
``postgresql://postgres@localhost:5432/agent_bridge_test``. The test creates and drops
its own schema; never point it at a real GraphRecall database.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

DB_URL = os.environ.get("AGENT_BRIDGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="AGENT_BRIDGE_TEST_DATABASE_URL not set")

MIGRATIONS = [Path(__file__).resolve().parents[1] / "db" / "migrations" / name
              for name in ("026_agent_bridge.sql", "027_agent_bridge_audit.sql")]


@pytest.fixture
async def pg():
    from sqlalchemy import text

    from backend.db.postgres_client import PostgresClient, PostgresSettings

    schema = f"ab_test_{uuid.uuid4().hex[:8]}"
    client = PostgresClient(PostgresSettings(database_url=DB_URL))
    await client.initialize()
    # Run everything in a private schema via search_path on every pooled connection.
    from sqlalchemy import event

    @event.listens_for(client._engine.sync_engine, "connect")
    def _set_path(dbapi_conn, _):  # pragma: no cover - driver hook
        cur = dbapi_conn.cursor()
        cur.execute(f"SET search_path TO {schema}, public")
        cur.close()

    async with client.session() as s:
        await s.execute(text(f"CREATE SCHEMA {schema}"))
    try:
        async with client.session() as s:
            await s.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
    except Exception:
        # Minimal local Postgres builds may lack uuid-ossp; shim it with the PG13+ builtin.
        async with client.session() as s:
            await s.execute(text(
                f"CREATE FUNCTION {schema}.uuid_generate_v4() RETURNS uuid "
                "LANGUAGE sql AS 'SELECT gen_random_uuid()'"))
    await client._engine.dispose()  # new connections pick up search_path
    async with client.session() as s:
        await s.execute(text(
            "CREATE TABLE users (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), "
            "email VARCHAR(255) UNIQUE NOT NULL, settings_json JSONB DEFAULT '{}'::jsonb)"))
        await s.execute(text(
            "CREATE TABLE chat_conversations (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), "
            "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE)"))
        # Twice: re-running must be a no-op (IF NOT EXISTS), e.g. on a database that
        # already ran the bridge's pre-merge 015/016 files.
        for _ in range(2):
            for mig in MIGRATIONS:
                for stmt in client._split_sql_statements(mig.read_text()):
                    await s.execute(text(stmt))
    try:
        yield client
    finally:
        async with client.session() as s:
            await s.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await client.close()


async def _user(pg, email):
    rows = await pg.execute_query("INSERT INTO users (email) VALUES (:e) RETURNING id", {"e": email})
    return str(rows[0]["id"])


def _feed(**kw):
    from backend.agent_bridge.dedupe import compute_dedupe_key

    base = {"item_kind": "article", "title": "T", "summary": "S", "source_kind": "web",
            "reason": "R", "source_url": "https://example.com/a", "concept_ids": ["c1"],
            "target_date": date(2026, 11, 25), "idempotency_key": None, "key_id": None}
    base.update(kw)
    base["dedupe_key"] = compute_dedupe_key(base["source_url"], base["title"], base["summary"])
    return base


async def test_keys_feed_dedupe_and_ownership(pg):
    from backend.agent_bridge.auth import authenticate_agent_key
    from backend.agent_bridge.repository import PostgresBridgeRepository

    repo = PostgresBridgeRepository(pg)
    ua, ub = await _user(pg, "a@x"), await _user(pg, "b@x")
    row, key = await repo.create_key(ua, "bot", ["read:knowledge", "write:feed"])
    p = await authenticate_agent_key(repo, key)
    assert p.user_id == ua and p.scopes == {"read:knowledge", "write:feed"}

    r1, c1 = await repo.insert_feed_item(ua, _feed(key_id=row["id"], idempotency_key="k1"))
    r2, c2 = await repo.insert_feed_item(ua, _feed(idempotency_key="k1", title="other",
                                                   source_url="https://example.com/zzz"))
    r3, c3 = await repo.insert_feed_item(ua, _feed(source_url="http://www.example.com/a/?utm_x=1"))
    r4, c4 = await repo.insert_feed_item(ub, _feed())
    assert c1 and not c2 and not c3 and c4
    assert r1["id"] == r2["id"] == r3["id"] != r4["id"]

    assert await repo.set_feed_item_status(ub, r1["id"], "approved") is None
    assert (await repo.set_feed_item_status(ua, r1["id"], "approved"))["status"] == "approved"
    assert [x["id"] for x in await repo.list_feed_items(ua, status="approved")] == [r1["id"]]
    assert await repo.owned_feed_item_ids(ub, [r1["id"]]) == set()

    d = await repo.upsert_digest(ua, {"digest_date": date(2026, 11, 25), "title": "a",
                                      "item_ids": [r1["id"]]})
    d2 = await repo.upsert_digest(ua, {"digest_date": date(2026, 11, 25), "title": "b",
                                       "item_ids": []})
    assert d["id"] == d2["id"] and (await repo.get_digest(ua, date(2026, 11, 25)))["title"] == "b"

    assert await repo.revoke_key(ub, row["id"]) is False
    assert await repo.revoke_key(ua, row["id"]) is True
    assert await authenticate_agent_key(repo, key) is None


async def test_concurrent_claim_is_atomic_and_lease_expires(pg):
    from backend.agent_bridge.repository import PostgresBridgeRepository

    repo = PostgresBridgeRepository(pg)
    ua, ub = await _user(pg, "a@x"), await _user(pg, "b@x")
    k, _ = await repo.create_key(ua, "bot", ["bridge:answer"])
    q = await repo.enqueue_request(ua, "Explain FSRS", {"topic": "srs"})

    assert await repo.claim_request(ub, k["id"]) is None  # other user's queue is empty
    results = await asyncio.gather(*[repo.claim_request(ua, k["id"]) for _ in range(20)])
    winners = [r for r in results if r]
    assert len(winners) == 1
    tok = winners[0]["claim_token"]

    assert await repo.complete_request(ub, q["id"], tok, answer_text="x") is None
    await pg.execute_update(
        "UPDATE agent_requests SET lease_expires_at = NOW() - INTERVAL '1 second' WHERE id = CAST(:id AS UUID)",
        {"id": q["id"]})
    assert await repo.complete_request(ua, q["id"], tok, answer_text="late") is None
    again = await repo.claim_request(ua, k["id"], request_id=q["id"], lease_seconds=60)
    assert again and again["claim_token"] != tok and again["attempts"] == 2
    done = await repo.complete_request(ua, q["id"], again["claim_token"], answer_text="ok",
                                       answer_json={"citations": []})
    assert done["status"] == "answered" and done["answer_json"] == {"citations": []}
    assert [r["id"] for r in await repo.list_requests(ua, statuses=["answered"])] == [q["id"]]

    q2 = await repo.enqueue_request(ua, "q2")
    assert await repo.cancel_request(ub, q2["id"]) is None
    assert (await repo.cancel_request(ua, q2["id"]))["status"] == "cancelled"


async def test_terminal_states_sweep_and_malformed_ids(pg):
    from backend.agent_bridge.repository import PostgresBridgeRepository

    repo = PostgresBridgeRepository(pg)
    ua, ub = await _user(pg, "a@x"), await _user(pg, "b@x")
    k, _ = await repo.create_key(ua, "bot", ["bridge:answer"])
    late = await repo.enqueue_request(ua, "late")
    hard = await repo.enqueue_request(ua, "hard")
    other = await repo.enqueue_request(ub, "b's")
    await pg.execute_update("UPDATE agent_requests SET expires_at = NOW() - INTERVAL '1 second' "
                            "WHERE id IN (CAST(:a AS UUID), CAST(:b AS UUID))",
                            {"a": late["id"], "b": other["id"]})
    for _ in range(3):
        c = await repo.claim_request(ua, k["id"], request_id=hard["id"])
        assert c
        await pg.execute_update("UPDATE agent_requests SET lease_expires_at = NOW() - "
                                "INTERVAL '1 second' WHERE id = CAST(:id AS UUID)", {"id": hard["id"]})
    # Lazy sweep is user-scoped: B's expired row is untouched until the global job runs.
    assert (await repo.get_request(ua, late["id"]))["status"] == "expired"
    h = await repo.get_request(ua, hard["id"])
    assert h["status"] == "failed" and h["claim_token"] is None and "3 attempts" in h["error"]
    raw = await pg.execute_query("SELECT status FROM agent_requests WHERE id = CAST(:id AS UUID)",
                                 {"id": other["id"]})
    assert raw[0]["status"] == "queued"
    from backend.agent_bridge.jobs import sweep_stale_requests

    assert await sweep_stale_requests(repo) == {"expired": 1, "failed": 0}
    assert (await repo.get_request(ub, other["id"]))["status"] == "expired"
    assert await repo.list_requests(ua, statuses=["queued", "claimed"]) == []

    for bad in ("nope", "1; drop table agent_requests", ""):
        assert await repo.get_request(ua, bad) is None
        assert await repo.cancel_request(ua, bad) is None
        assert await repo.claim_request(ua, k["id"], request_id=bad) is None
        assert await repo.complete_request(ua, late["id"], bad, answer_text="x") is None
        assert await repo.set_feed_item_status(ua, bad, "approved") is None
        assert await repo.conversation_owned(ua, bad) is False


async def test_feed_state_machine_batch_atomicity_cap_audit(pg):
    from backend.agent_bridge.limits import PostgresRateLimiter
    from backend.agent_bridge.repository import (
        InvalidTransitionError,
        LimitExceededError,
        PostgresBridgeRepository,
    )

    repo = PostgresBridgeRepository(pg)
    ua, ub = await _user(pg, "a@x"), await _user(pg, "b@x")
    rows = await repo.insert_feed_items(ua, [_feed(source_url="https://e.com/1"),
                                             _feed(source_url="https://e.com/2"),
                                             _feed(source_url="https://e.com/1")])
    assert [c for _, c in rows] == [True, True, False] and rows[0][0]["id"] == rows[2][0]["id"]

    # Cap: 2 pending already; a batch of 2 new with cap 3 is rejected as a whole.
    with pytest.raises(LimitExceededError):
        await repo.insert_feed_items(ua, [_feed(source_url="https://e.com/3"),
                                          _feed(source_url="https://e.com/4")],
                                     max_pending_today=3)
    # A failing statement mid-batch rolls the batch back too (bad source_kind -> CHECK).
    with pytest.raises(Exception):
        await repo.insert_feed_items(ua, [_feed(source_url="https://e.com/5"),
                                          _feed(source_url="https://e.com/6", source_kind="??")])
    assert len(await repo.list_feed_items(ua, status=None)) == 2

    a_id, b_id = rows[0][0]["id"], rows[1][0]["id"]
    assert (await repo.set_feed_item_status(ua, a_id, "rejected"))["status"] == "rejected"
    with pytest.raises(InvalidTransitionError):
        await repo.set_feed_item_status(ua, a_id, "approved")
    assert (await repo.set_feed_item_status(ua, b_id, "approved"))["status"] == "approved"
    again = await repo.set_feed_item_status(ua, b_id, "approved")
    assert again["status"] == "approved"
    assert await repo.set_feed_item_status(ub, b_id, "rejected") is None

    conv = await pg.execute_query("INSERT INTO chat_conversations (user_id) "
                                  "VALUES (CAST(:u AS UUID)) RETURNING id", {"u": ua})
    cid = str(conv[0]["id"])
    assert await repo.conversation_owned(ua, cid) and not await repo.conversation_owned(ub, cid)

    await repo.audit(ua, "tool_call", actor="agent", key_id=None, tool="search_concepts",
                     target_id="not-a-uuid", details={"concepts_count": 2})
    ev = await repo.list_audit(ua)
    assert ev[0]["tool"] == "search_concepts" and ev[0]["details"] == {"concepts_count": 2}
    assert await repo.list_audit(ub) == []

    lim1, lim2 = PostgresRateLimiter(pg), PostgresRateLimiter(pg)
    results = await asyncio.gather(*[(lim1 if i % 2 else lim2).hit("t", 5, 3600)
                                     for i in range(8)])
    assert sum(results) == 5
