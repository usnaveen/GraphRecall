"""GR-SEC-03: checkpoint threads carry their owner, and nobody can load or resume another user's.

Before: POST /api/chat used the client's conversation_id as the LangGraph thread id with no
ownership check, so user B could load user A's message state (and append to it) by sending A's
conversation id. Ingestion status/approve trusted the thread id the same way.
"""

import uuid

import pytest
from fastapi import HTTPException

from backend.graphs.thread_ids import chat_thread_id, ingest_thread_id, thread_belongs_to, user_thread_prefixes
from backend.models.feed_schemas import ChatRequest
from backend.tests.test_migrate import scratch_db  # noqa: F401

pytestmark = pytest.mark.asyncio


def test_thread_ids_carry_their_owner():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    t = chat_thread_id(a, "conv-1")
    assert t == f"chat:{a}:conv-1" and thread_belongs_to(t, a) and not thread_belongs_to(t, b)
    i = ingest_thread_id(a)
    assert thread_belongs_to(i, a) and not thread_belongs_to(i, b)
    assert not thread_belongs_to("conv-1", a)  # bare ids from before the change belong to nobody
    assert all(p.endswith(f"{a}:") for p in user_thread_prefixes(a))


@pytest.fixture
async def chat_env(scratch_db, monkeypatch):  # noqa: F811
    from backend.db import migrate as M
    from backend.routers import chat

    pg, _ = scratch_db
    await M.migrate(pg)
    users = []
    for tag in ("a", "b"):
        await pg.execute_update("INSERT INTO users (email) VALUES (:e)", {"e": f"thr-{tag}-{uuid.uuid4().hex[:6]}@example.invalid"})
    rows = await pg.execute_query("SELECT id FROM users ORDER BY created_at DESC LIMIT 2")
    users = [str(r["id"]) for r in rows]
    conv = await pg.execute_insert(
        "INSERT INTO chat_conversations (user_id, title) VALUES (CAST(:u AS uuid), 'a private chat') RETURNING id",
        {"u": users[0]})

    async def get_pg():
        return pg
    calls = []

    async def fake_run_chat(*, user_id, message, thread_id):
        calls.append(thread_id)
        return {"response": "ok", "sources": [], "related_concepts": []}
    monkeypatch.setattr(chat, "get_postgres_client", get_pg)
    monkeypatch.setattr(chat, "run_chat", fake_run_chat)
    return chat, users[0], users[1], str(conv), calls


async def test_cannot_chat_in_another_users_conversation(chat_env):
    chat, owner, other, conv, calls = chat_env
    req = ChatRequest(user_id=other, message="what did they say?", conversation_id=conv)
    with pytest.raises(HTTPException) as e:
        await chat.chat(req, current_user={"id": other})
    assert e.value.status_code == 404 and calls == []


async def test_owner_chats_in_own_namespaced_thread(chat_env):
    chat, owner, other, conv, calls = chat_env
    await chat.chat(ChatRequest(user_id=owner, message="hi", conversation_id=conv), current_user={"id": owner})
    assert calls == [f"chat:{owner}:{conv}"]


@pytest.mark.parametrize("endpoint", ["status", "events", "approve"])
async def test_cannot_read_or_resume_another_users_ingestion(endpoint, monkeypatch):
    from backend.routers import ingest_v2

    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    thread = ingest_thread_id(a)

    async def must_not_run(*args, **kwargs):
        raise AssertionError("reached the graph with someone else's thread")
    monkeypatch.setattr(ingest_v2, "get_ingestion_status", must_not_run)
    monkeypatch.setattr(ingest_v2, "resume_ingestion", must_not_run)
    with pytest.raises(HTTPException) as e:
        if endpoint == "status":
            await ingest_v2.get_status(thread, current_user={"id": b})
        elif endpoint == "events":
            await ingest_v2.get_processed_zip_events(thread, current_user={"id": b})
        else:
            await ingest_v2.approve_and_resume(thread, ingest_v2.ResumeRequest(approved_concepts=[]),
                                               current_user={"id": b})
    assert e.value.status_code == 404
