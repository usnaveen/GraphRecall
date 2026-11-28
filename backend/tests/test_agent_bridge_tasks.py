"""MCP Tasks on the agent bridge: the task store and runner, the ingest jobs, and the wire protocol."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import httpx
import pytest

from backend.agent_bridge import ingest_jobs, tasks
from backend.agent_bridge.keys import AgentPrincipal
from backend.agent_bridge.repository import InMemoryBridgeRepository
from backend.agent_bridge.tools import BridgeServices, LearningSessionArgs, call_tool

U1, U2 = "00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000b2"
INGEST = frozenset({"read:knowledge", "write:ingest"})


async def _settle(store, user, task_id, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        row = await store.get(user, task_id)
        if row["status"] in tasks.TERMINAL:
            return row
        await asyncio.sleep(0.01)
    raise AssertionError("task did not finish")


# --- store + runner ------------------------------------------------------------------------------

async def test_task_runs_in_background_and_completes():
    store, gate = tasks.InMemoryTaskStore(), asyncio.Event()

    async def work(progress):
        await progress("halfway")
        await gate.wait()
        return tasks.tool_result({"done": True})

    row = await tasks.start(store, user_id=U1, key_id=None, tool="ingest_link", work=work, first_message="Queued")
    assert row["status"] == "working" and row["id"].startswith("grt_") and len(row["id"]) <= 128
    await asyncio.sleep(0.02)
    assert (await store.get(U1, row["id"]))["status_message"] == "halfway"
    gate.set()
    done = await _settle(store, U1, row["id"])
    wire = tasks.wire(done, result_type="complete")
    assert wire["status"] == "completed" and wire["resultType"] == "complete"
    assert wire["result"]["structuredContent"] == {"done": True} and wire["result"]["isError"] is False
    assert {"taskId", "createdAt", "lastUpdatedAt", "ttlMs", "pollIntervalMs"} <= wire.keys()
    assert wire["ttlMs"] >= 3_600_000 + 30 * 60_000  # longest run + at least an hour kept


async def test_exception_is_failed_with_jsonrpc_error_and_tool_error_is_completed():
    store = tasks.InMemoryTaskStore()

    async def boom(progress):
        raise RuntimeError("secret detail")

    async def partial(progress):
        return tasks.tool_result({"imported": 0}, is_error=True)

    a = await tasks.start(store, user_id=U1, key_id=None, tool="t", work=boom, first_message="")
    b = await tasks.start(store, user_id=U1, key_id=None, tool="t", work=partial, first_message="")
    fa, fb = tasks.wire(await _settle(store, U1, a["id"]), result_type="complete"), \
        tasks.wire(await _settle(store, U1, b["id"]), result_type="complete")
    assert fa["status"] == "failed" and fa["error"]["code"] == -32603 and "secret" not in json.dumps(fa)
    assert fb["status"] == "completed" and fb["result"]["isError"] is True


async def test_cancel_and_foreign_or_unknown_ids():
    store = tasks.InMemoryTaskStore()

    async def forever(progress):
        await asyncio.sleep(60)
        return tasks.tool_result({})

    row = await tasks.start(store, user_id=U1, key_id=None, tool="t", work=forever, first_message="")
    with pytest.raises(tasks.TaskNotFound):
        await tasks.get(store, U2, row["id"])  # another user's id looks unknown
    with pytest.raises(tasks.TaskNotFound):
        await tasks.cancel(store, U2, row["id"])
    with pytest.raises(tasks.TaskNotFound):
        await tasks.get(store, U1, "grt_nope")
    await tasks.cancel(store, U1, row["id"])
    assert (await _settle(store, U1, row["id"]))["status"] == "cancelled"


async def test_expired_and_orphaned_tasks():
    store = tasks.InMemoryTaskStore()
    await store.create("grt_old", U1, None, "t", None)
    store.rows["grt_old"]["expires_at"] -= tasks.MAX_RUN + tasks.RETAIN + timedelta(seconds=1)
    with pytest.raises(tasks.TaskNotFound):
        await tasks.get(store, U1, "grt_old")
    await store.create("grt_orphan", U1, None, "t", None)  # 'working', but no job in this process
    store.rows["grt_orphan"]["updated_at"] -= tasks.MAX_RUN + timedelta(seconds=1)
    row = await tasks.get(store, U1, "grt_orphan")
    assert row["status"] == "failed" and row["error"]["code"] == -32603
    assert await store.count_active(U1) == 0


async def test_concurrent_task_cap():
    store, gate = tasks.InMemoryTaskStore(), asyncio.Event()

    async def wait(progress):
        await gate.wait()
        return tasks.tool_result({})

    for _ in range(tasks.MAX_ACTIVE_PER_USER):
        await tasks.start(store, user_id=U1, key_id=None, tool="t", work=wait, first_message="")
    with pytest.raises(tasks.TooManyTasks):
        await tasks.start(store, user_id=U1, key_id=None, tool="t", work=wait, first_message="")
    await tasks.start(store, user_id=U2, key_id=None, tool="t", work=wait, first_message="")  # per user
    gate.set()
    await asyncio.sleep(0.05)


# --- the learning-session job --------------------------------------------------------------------

def test_session_note_and_transcript_cap():
    md, cut = ingest_jobs.render_session_note(
        "KV caching", "## Why\nThe cache avoids recomputing keys.", ["attention"],
        [{"concept": "KV cache growth", "why": "didn't see why it grows"}],
        [{"url": "https://example.com/a", "title": "A", "note": "intro"}], "Q" * 40_000, "via MCP")
    assert md.startswith("# KV caching") and "saved by your agent" in md
    assert "- **KV cache growth**: didn't see why it grows" in md and "[A](https://example.com/a): intro" in md
    assert cut and "Conversation (excerpt)" in md and md.count("Q") == ingest_jobs.TRANSCRIPT_CAP


def test_video_links_are_detected():
    assert ingest_jobs.is_video("https://www.youtube.com/watch?v=aircAruvnKk")
    assert ingest_jobs.is_video("https://youtu.be/aircAruvnKk")
    assert not ingest_jobs.is_video("https://lilianweng.github.io/posts/attention/")


class _Knowledge:
    def __init__(self, known):
        self.known, self.calls = known, []

    async def record_exposure(self, user_id, concept, context, **kw):
        self.calls.append((concept, kw["confidence"], context))
        return {"concept": concept, "concept_id": "c1" if concept in self.known else None}


async def test_learning_session_job(monkeypatch):
    import importlib

    ig = importlib.import_module("backend.graphs.ingestion_graph")  # the package re-exports a same-named graph

    seen = {}

    async def fake_ingest(**kw):
        seen.update(kw)
        return {"note_id": "n1", "status": "completed", "concepts": [{"name": "attention"}]}

    async def fake_link(user_id, url):
        return {"url": url, "status": "duplicate" if "dup" in url else "imported", "note_id": "n2"}

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(ig, "run_ingestion", fake_ingest)
    monkeypatch.setattr(ingest_jobs, "import_link", fake_link)
    monkeypatch.setattr(ingest_jobs, "_charge", nothing)
    monkeypatch.setattr(ingest_jobs, "_after_ingest", nothing)

    async def saved(user_id, note_id):
        return True

    monkeypatch.setattr(ingest_jobs, "_note_saved", saved)
    know, msgs = _Knowledge({"attention", "KV cache growth"}), []

    async def progress(m):
        msgs.append(m)

    res = await ingest_jobs.run_learning_session(
        U1, know, agent_name="via MCP", topic="KV caching", summary="key details", learned=["attention", "rope"],
        struggled=[{"concept": "KV cache growth", "why": "why it grows"}],
        resources=[{"url": "https://e.com/a", "title": "A"}, {"url": "https://e.com/dup"}], transcript=None,
        progress=progress)
    out = res["structuredContent"]
    assert res["isError"] is False and out["session_note"]["note_id"] == "n1"
    assert seen["skip_review"] is True and seen["resource_type"] == "chat_conversation"
    assert [r["status"] for r in out["resources"]] == ["imported", "duplicate"]
    assert out["evidence"] == {"learned": ["attention"], "struggled": ["KV cache growth"], "not_in_graph": ["rope"]}
    signals = {c: s for c, s, _ in know.calls}
    assert signals["KV cache growth"] < signals["attention"]
    assert any(m.startswith("Reading 2 of 2") for m in msgs)


def test_session_resource_type_is_allowed_by_the_notes_table():
    import re
    from pathlib import Path

    sql = " ".join(p.read_text() for p in Path("backend/db").rglob("*.sql"))
    allowed = re.findall(r"'([a-z_]+)'", sql[sql.find("valid_resource_type"):][:600])
    assert ingest_jobs.SESSION_RESOURCE_TYPE in allowed


async def test_unsaved_note_is_reported_as_error(monkeypatch):
    import importlib

    ig = importlib.import_module("backend.graphs.ingestion_graph")

    async def fake_ingest(**kw):
        return {"note_id": "n1", "status": "completed"}  # what the pipeline returns when storing failed

    async def nothing(*a, **k):
        return None

    async def not_saved(user_id, note_id):
        return False

    monkeypatch.setattr(ig, "run_ingestion", fake_ingest)
    monkeypatch.setattr(ingest_jobs, "_charge", nothing)
    monkeypatch.setattr(ingest_jobs, "_note_saved", not_saved)
    res = await ingest_jobs.run_learning_session(
        U1, _Knowledge(set()), agent_name="x", topic="t", summary="s", learned=[], struggled=[], resources=[],
        transcript=None, progress=nothing)
    assert res["structuredContent"]["session_note"]["status"] == "error" and res["isError"] is True


def test_session_args_validation():
    with pytest.raises(Exception):
        LearningSessionArgs(topic="x")  # nothing to save
    with pytest.raises(Exception):
        LearningSessionArgs(topic="x", resources=[{"url": "javascript:alert(1)"}])
    LearningSessionArgs(topic="x", learned=["a"])


async def test_tool_scope_and_status_tool(monkeypatch):
    async def quick(user_id, url, progress):
        return tasks.tool_result({"url": url, "status": "imported"})

    monkeypatch.setattr(ingest_jobs, "run_ingest_link", quick)
    svc = BridgeServices(repo=InMemoryBridgeRepository(), knowledge=None)  # type: ignore[arg-type]
    read_only = AgentPrincipal(user_id=U1, key_id="k", scopes=frozenset({"read:knowledge"}))
    res = await call_tool("ingest_link", read_only, svc, {"url": "https://example.com/a"})
    assert res["ok"] is False and res["error"]["code"] == "forbidden"
    p = AgentPrincipal(user_id=U1, key_id="k", scopes=INGEST)
    started = await call_tool("ingest_link", p, svc, {"url": "https://example.com/a"})
    assert started["ok"] and started["data"]["status"] == "working"
    await _settle(svc.tasks, U1, started["data"]["task_id"])
    status = await call_tool("get_ingest_status", p, svc, {"task_id": started["data"]["task_id"]})
    assert status["data"]["status"] == "completed" and status["data"]["result"]["status"] == "imported"
    other = AgentPrincipal(user_id=U2, key_id="k2", scopes=INGEST)
    assert (await call_tool("get_ingest_status", other, svc, {"task_id": started["data"]["task_id"]}))["error"]["code"] == "not_found"


# --- the wire protocol over Streamable HTTP --------------------------------------------------------

def _meta(with_tasks: bool) -> dict:
    caps = {"extensions": {tasks.EXTENSION_ID: {}}} if with_tasks else {}
    return {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"},
            "io.modelcontextprotocol/clientCapabilities": caps}


async def test_wire_protocol_over_http(monkeypatch):
    pytest.importorskip("mcp.server.streamable_http_manager")
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    from backend.agent_bridge import mcp_app

    gate = asyncio.Event()

    async def slow(user_id, url, progress):
        await gate.wait()
        return tasks.tool_result({"url": url, "status": "imported"})

    monkeypatch.setattr(ingest_jobs, "run_ingest_link", slow)
    svc = BridgeServices(repo=InMemoryBridgeRepository(), knowledge=None)  # type: ignore[arg-type]

    async def factory():
        return svc

    mgr = StreamableHTTPSessionManager(app=mcp_app.build_lowlevel_server(factory), stateless=True, json_response=True)
    who = {"p": AgentPrincipal(user_id=U1, key_id="k", scopes=INGEST)}

    async def app(scope, receive, send):
        scope.setdefault("state", {})["agent_principal"] = who["p"]
        await mgr.handle_request(scope, receive, send)

    async def rpc(c, method, params, with_tasks=True, name=None):
        h = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method}
        if name:
            h["Mcp-Name"] = name
        r = await c.post("http://t/", json={"jsonrpc": "2.0", "id": 1, "method": method,
                                            "params": {**params, "_meta": _meta(with_tasks)}}, headers=h)
        return r.json()

    async with mgr.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as c:
            caps = (await rpc(c, "server/discover", {}))["result"]["capabilities"]["extensions"]
            assert tasks.EXTENSION_ID in caps and "io.modelcontextprotocol/skills" in caps

            created = (await rpc(c, "tools/call", {"name": "ingest_link", "arguments": {"url": "https://e.com/a"}},
                                 name="ingest_link"))["result"]
            assert created["resultType"] == "task" and created["status"] == "working"
            tid = created["taskId"]
            got = (await rpc(c, "tasks/get", {"taskId": tid}, name=tid))["result"]
            assert got["resultType"] == "complete" and got["status"] == "working"
            gate.set()
            await _settle(svc.tasks, U1, tid)
            got = (await rpc(c, "tasks/get", {"taskId": tid}, name=tid))["result"]
            assert got["status"] == "completed" and got["result"]["structuredContent"]["status"] == "imported"

            # A client that didn't declare the extension never gets a task, and can't call tasks/*.
            plain = (await rpc(c, "tools/call", {"name": "ingest_link", "arguments": {"url": "https://e.com/b"}},
                               with_tasks=False, name="ingest_link"))["result"]
            assert plain.get("resultType") != "task" and "task_id" in plain["content"][0]["text"]
            assert (await rpc(c, "tasks/get", {"taskId": tid}, with_tasks=False, name=tid))["error"]["code"] == -32021

            # Another user's key: the task doesn't exist for them.
            who["p"] = AgentPrincipal(user_id=U2, key_id="k2", scopes=INGEST)
            assert (await rpc(c, "tasks/get", {"taskId": tid}, name=tid))["error"]["code"] == -32602
            assert (await rpc(c, "tasks/cancel", {"taskId": tid}, name=tid))["error"]["code"] == -32602
            who["p"] = AgentPrincipal(user_id=U1, key_id="k", scopes=INGEST)
            ack = (await rpc(c, "tasks/cancel", {"taskId": tid}, name=tid))["result"]
            assert ack["resultType"] == "complete"  # already finished: cancel is a no-op ack
