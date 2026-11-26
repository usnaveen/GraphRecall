"""Agent bridge: auth scopes, ownership isolation, idempotent feed proposals,
atomic question claims, MCP-over-HTTP wiring, REST endpoints."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from backend.agent_bridge.auth import SlidingWindowLimiter, authenticate_agent_key
from backend.agent_bridge.dedupe import compute_dedupe_key, normalize_url
from backend.agent_bridge.feed_integration import agent_feed_items, to_feed_item
from backend.agent_bridge.keys import (
    SCOPE_BRIDGE_ANSWER,
    SCOPE_READ_KNOWLEDGE,
    SCOPE_WRITE_FEED,
    AgentPrincipal,
    InvalidScopeError,
    generate_key,
    parse_key_prefix,
    validate_scopes,
)
from backend.agent_bridge.knowledge import KnowledgeService
from backend.agent_bridge.repository import InMemoryBridgeRepository
from backend.agent_bridge.tools import TOOLS, BridgeServices, call_tool
from backend.agent_bridge.webhook import sign_payload, verify_signature
from backend.models.feed_schemas import FeedItemType
from backend.tests.agent_bridge_fakes import USER_A, USER_B, FakeNeo4j, FakePG

ALL = frozenset({SCOPE_READ_KNOWLEDGE, SCOPE_WRITE_FEED, SCOPE_BRIDGE_ANSWER})


@pytest.fixture
def repo():
    return InMemoryBridgeRepository()


@pytest.fixture
def fakes():
    return FakePG(), FakeNeo4j()


@pytest.fixture
def services(repo, fakes):
    pg, neo = fakes
    return BridgeServices(repo=repo, knowledge=KnowledgeService(pg, neo))


def principal(user=USER_A, scopes=ALL, key_id="key-a"):
    return AgentPrincipal(user_id=user, key_id=key_id, scopes=frozenset(scopes))


def item(**kw):
    base = {"title": "Attention is all you need, explained", "summary": "Short curated summary",
            "reason": "You have a transformer exam on Friday",
            "source_url": "https://example.substack.com/p/attention?utm_source=email",
            "source_kind": "substack", "target_date": "2026-11-25"}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Keys + auth
# ---------------------------------------------------------------------------


def test_key_format_and_prefix():
    k = generate_key()
    assert k.full_key.startswith(k.key_prefix + "_")
    assert parse_key_prefix(k.full_key) == k.key_prefix
    assert len(k.key_hash) == 64 and k.full_key not in k.key_hash
    assert parse_key_prefix("eyJhbGciOi.jwt.token") is None
    assert parse_key_prefix("grk__secret") is None


def test_validate_scopes():
    assert validate_scopes(["write:feed", "read:knowledge"]) == ["read:knowledge", "write:feed"]
    with pytest.raises(InvalidScopeError):
        validate_scopes(["admin"])
    with pytest.raises(InvalidScopeError):
        validate_scopes([])


async def test_authenticate_valid_revoked_expired_and_tampered(repo):
    row, key = await repo.create_key(USER_A, "bot", [SCOPE_READ_KNOWLEDGE])
    assert "key_hash" not in row
    p = await authenticate_agent_key(repo, key)
    assert p and p.user_id == USER_A and p.scopes == {SCOPE_READ_KNOWLEDGE}

    assert await authenticate_agent_key(repo, key[:-2] + "xx") is None  # wrong secret
    assert await authenticate_agent_key(repo, None) is None
    assert await authenticate_agent_key(repo, "not-a-key") is None

    assert await repo.revoke_key(USER_B, row["id"]) is False  # other user cannot revoke
    assert await repo.revoke_key(USER_A, row["id"]) is True
    assert await authenticate_agent_key(repo, key) is None

    _, key2 = await repo.create_key(USER_A, "old", [SCOPE_READ_KNOWLEDGE],
                                    expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert await authenticate_agent_key(repo, key2) is None


@pytest.mark.parametrize("tool,scope,args", [
    ("get_knowledge_profile", SCOPE_READ_KNOWLEDGE, {}),
    ("search_concepts", SCOPE_READ_KNOWLEDGE, {"query": "grad"}),
    ("propose_feed_items", SCOPE_WRITE_FEED, {"items": [item()]}),
    ("schedule_daily_digest", SCOPE_WRITE_FEED, {"title": "Today"}),
    ("list_pending_questions", SCOPE_BRIDGE_ANSWER, {}),
    ("claim_question", SCOPE_BRIDGE_ANSWER, {}),
])
async def test_every_tool_requires_its_scope(services, tool, scope, args):
    assert TOOLS[tool].scope == scope
    without = principal(scopes=ALL - {scope})
    res = await call_tool(tool, without, services, args)
    assert res["ok"] is False and res["error"]["code"] == "forbidden"
    res = await call_tool(tool, principal(scopes={scope}), services, args)
    assert res["ok"] is True, res


async def test_tools_reject_user_id_argument(services):
    # A caller cannot pick a user: unknown args are rejected outright.
    res = await call_tool("search_concepts", principal(), services,
                          {"query": "sql", "user_id": USER_B})
    assert res["ok"] is False and res["error"]["code"] == "invalid_arguments"


def test_rate_limiter():
    lim = SlidingWindowLimiter(max_calls=2, window_seconds=10)
    assert lim.allow("k", 0) and lim.allow("k", 1)
    assert not lim.allow("k", 2)
    assert lim.allow("other", 2)
    assert lim.allow("k", 11)


# ---------------------------------------------------------------------------
# Ownership isolation
# ---------------------------------------------------------------------------


async def test_reads_are_scoped_to_key_owner(services, fakes):
    b = principal(USER_B, key_id="key-b")
    res = await call_tool("search_concepts", b, services, {"query": "a"})
    names = {c["name"] for c in res["data"]["concepts"]}
    assert "Alice Private Topic" not in names and "Backpropagation" not in names

    prof = (await call_tool("get_knowledge_profile", b, services, {}))["data"]
    assert prof["total_concepts"] == 2
    ids = {c["id"] for c in prof["weak_concepts"] + prof["strong_concepts"]}
    assert ids <= {"b-sql", "b-index"}

    due = (await call_tool("list_due_reviews", b, services, {}))["data"]["due"]
    assert {d["id"] for d in due} == {"b-sql", "b-index"}

    act = (await call_tool("get_recent_activity", b, services, {}))["data"]
    assert {r["concept_id"] for r in act["reviews"]} == {"b-sql", "b-index"}

    # Another user's concept looks exactly like a missing one.
    res = await call_tool("get_concept_neighborhood", b, services, {"concept_id": "a-secret"})
    assert res["ok"] is False and res["error"]["code"] == "not_found"

    # Own concept: neighbours never cross users even if a cross-user edge exists.
    res = await call_tool("get_concept_neighborhood", b, services, {"concept_id": "b-sql"})
    assert {n["id"] for n in res["data"]["neighbors"]} == {"b-index"}

    pg, neo = fakes
    for q, params in pg.calls + neo.calls:
        assert params.get("user_id") == USER_B, q


async def test_writes_cannot_touch_other_users_data(services, repo):
    a, b = principal(USER_A), principal(USER_B, key_id="key-b")

    # B tags A's concept -> dropped, not linked.
    res = await call_tool("propose_feed_items", b, services,
                          {"items": [item(concept_ids=["a-secret", "b-sql"])]})
    r = res["data"]["items"][0]
    assert r["dropped_concept_ids"] == ["a-secret"]
    assert repo.feed[r["id"]]["concept_ids"] == ["b-sql"]

    a_item = (await call_tool("propose_feed_items", a, services, {"items": [item()]}))["data"]["items"][0]
    # B cannot reference A's feed item in a digest.
    res = await call_tool("schedule_daily_digest", b, services,
                          {"title": "x", "item_ids": [a_item["id"]]})
    assert res["ok"] is False and res["error"]["code"] == "not_found"
    # B cannot approve A's item.
    assert await repo.set_feed_item_status(USER_B, a_item["id"], "approved") is None
    assert repo.feed[a_item["id"]]["status"] == "pending"
    assert all(i["user_id"] == USER_B for i in await repo.list_feed_items(USER_B, status=None))


async def test_questions_are_scoped_to_key_owner(services, repo):
    q = await repo.enqueue_request(USER_A, "Explain my weakest ML topic")
    b = principal(USER_B, key_id="key-b")
    listed = (await call_tool("list_pending_questions", b, services, {}))["data"]["questions"]
    assert listed == []
    res = await call_tool("claim_question", b, services, {"request_id": q["id"]})
    assert res["data"]["claimed"] is False

    a = principal(USER_A)
    claimed = (await call_tool("claim_question", a, services, {}))["data"]["question"]
    # B cannot submit even with A's valid claim token.
    res = await call_tool("submit_answer", b, services, {
        "request_id": q["id"], "claim_token": claimed["claim_token"], "answer_markdown": "pwned"})
    assert res["ok"] is False and res["error"]["code"] == "conflict"
    assert (await repo.get_request(USER_A, q["id"]))["status"] == "claimed"
    assert await repo.get_request(USER_B, q["id"]) is None


# ---------------------------------------------------------------------------
# Idempotent feed proposals
# ---------------------------------------------------------------------------


def test_normalize_url():
    assert normalize_url("HTTP://www.Example.com/p/x/?utm_source=a&b=2&a=1#frag") == \
        "https://example.com/p/x?a=1&b=2"
    assert normalize_url("javascript:alert(1)") is None
    assert compute_dedupe_key(None, "T", "S") == compute_dedupe_key(None, " t ", "s")


async def test_propose_is_idempotent(services, repo):
    a = principal()
    first = (await call_tool("propose_feed_items", a, services,
                             {"items": [item(idempotency_key="nightly-2026-11-25-1")]}))["data"]["items"][0]
    assert first["created"] is True and first["status"] == "pending"

    # Retry with the same idempotency key (even with edited text) -> same row.
    again = (await call_tool("propose_feed_items", a, services, {"items": [item(
        idempotency_key="nightly-2026-11-25-1", title="edited", source_url=None)]}))["data"]["items"][0]
    assert again["id"] == first["id"] and again["created"] is False

    # Same article, different tracking params / scheme, same day -> deduped.
    dup = (await call_tool("propose_feed_items", a, services, {"items": [item(
        source_url="http://example.substack.com/p/attention/?utm_campaign=x")]}))["data"]["items"][0]
    assert dup["id"] == first["id"] and dup["deduplicated"] is True

    # Same article on another day is a new card.
    other_day = (await call_tool("propose_feed_items", a, services,
                                 {"items": [item(target_date="2026-11-26")]}))["data"]["items"][0]
    assert other_day["id"] != first["id"]

    # Same article for a different user is independent.
    b_item = (await call_tool("propose_feed_items", principal(USER_B, key_id="key-b"), services,
                              {"items": [item()]}))["data"]["items"][0]
    assert b_item["created"] is True

    # No-URL items dedupe on content.
    n1 = (await call_tool("propose_feed_items", a, services, {"items": [item(
        source_url=None, title="Exam tip", summary="Review SM-2")]}))["data"]["items"][0]
    n2 = (await call_tool("propose_feed_items", a, services, {"items": [item(
        source_url=None, title="exam tip ", summary="review  sm-2")]}))["data"]["items"][0]
    assert n1["id"] == n2["id"]
    assert len([r for r in repo.feed.values() if r["user_id"] == USER_A]) == 3


async def test_propose_validation(services):
    a = principal()
    res = await call_tool("propose_feed_items", a, services,
                          {"items": [item(source_url="ftp://x")]})
    assert res["error"]["code"] == "invalid_arguments"
    res = await call_tool("propose_feed_items", a, services, {"items": [item()] * 21})
    assert res["error"]["code"] == "invalid_arguments"
    res = await call_tool("propose_feed_items", a, services,
                          {"items": [item(item_kind="flashcard")]})
    assert res["error"]["code"] == "invalid_arguments"


async def test_digest_upsert(services):
    a = principal()
    it = (await call_tool("propose_feed_items", a, services, {"items": [item()]}))["data"]["items"][0]
    d1 = await call_tool("schedule_daily_digest", a, services, {
        "digest_date": "2026-11-25", "title": "Exam prep", "item_ids": [it["id"]],
        "focus_concept_ids": ["a-backprop", "b-sql"]})
    d2 = await call_tool("schedule_daily_digest", a, services, {
        "digest_date": "2026-11-25", "title": "Exam prep v2", "item_ids": [it["id"]]})
    assert d1["data"]["digest"]["id"] == d2["data"]["digest"]["id"]
    stored = await services.repo.get_digest(USER_A, date(2026, 11, 25))
    assert stored["title"] == "Exam prep v2"


# ---------------------------------------------------------------------------
# Question queue: atomic claim + lease
# ---------------------------------------------------------------------------


async def test_queue_lifecycle(services, repo):
    a = principal()
    q = await repo.enqueue_request(USER_A, "What should I revise for my DBMS exam?",
                                   {"topic": "DBMS"})
    listed = (await call_tool("list_pending_questions", a, services, {}))["data"]["questions"]
    assert [x["id"] for x in listed] == [q["id"]] and listed[0]["claimable"]

    c = (await call_tool("claim_question", a, services, {}))["data"]
    assert c["claimed"] and c["question"]["claim_token"]
    # Already claimed -> nothing else to claim.
    assert (await call_tool("claim_question", a, services, {}))["data"]["claimed"] is False

    res = await call_tool("submit_answer", a, services, {
        "request_id": q["id"], "claim_token": c["question"]["claim_token"],
        "answer_markdown": "Focus on normalization.",
        "citations": [{"title": "Notes", "url": "https://example.com"}]})
    assert res["ok"] and res["data"]["status"] == "answered"
    stored = await repo.get_request(USER_A, q["id"])
    assert stored["answer_text"] == "Focus on normalization."
    assert stored["answer_json"]["citations"][0]["title"] == "Notes"
    # Double submit -> conflict.
    res = await call_tool("submit_answer", a, services, {
        "request_id": q["id"], "claim_token": c["question"]["claim_token"],
        "answer_markdown": "again"})
    assert res["error"]["code"] == "conflict"


async def test_concurrent_claims_have_exactly_one_winner(repo):
    q = await repo.enqueue_request(USER_A, "q")
    results = await asyncio.gather(*[
        repo.claim_request(USER_A, f"key-{i}", request_id=q["id"]) for i in range(25)])
    winners = [r for r in results if r]
    assert len(winners) == 1


async def test_lease_expiry_allows_reclaim_and_invalidates_old_token(repo):
    q = await repo.enqueue_request(USER_A, "q")
    first = await repo.claim_request(USER_A, "key-1", lease_seconds=60)
    repo.requests[q["id"]]["lease_expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    # Expired lease: the original holder can no longer submit...
    assert await repo.complete_request(USER_A, q["id"], first["claim_token"], answer_text="x") is None
    # ...and another worker may reclaim with a new token.
    second = await repo.claim_request(USER_A, "key-2")
    assert second and second["claim_token"] != first["claim_token"] and second["attempts"] == 2
    assert await repo.complete_request(USER_A, q["id"], first["claim_token"], answer_text="x") is None
    done = await repo.complete_request(USER_A, q["id"], second["claim_token"], answer_text="ok")
    assert done["status"] == "answered"


async def test_max_attempts_and_cancel(repo):
    q = await repo.enqueue_request(USER_A, "q")
    for _ in range(3):
        assert await repo.claim_request(USER_A, "k", max_attempts=3)
        repo.requests[q["id"]]["lease_expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await repo.claim_request(USER_A, "k", max_attempts=3) is None
    q2 = await repo.enqueue_request(USER_A, "q2")
    assert await repo.cancel_request(USER_B, q2["id"]) is None
    assert (await repo.cancel_request(USER_A, q2["id"]))["status"] == "cancelled"
    assert await repo.claim_request(USER_A, "k", request_id=q2["id"]) is None


async def test_submit_error_marks_failed(services, repo):
    a = principal()
    q = await repo.enqueue_request(USER_A, "q")
    c = (await call_tool("claim_question", a, services, {}))["data"]["question"]
    res = await call_tool("submit_answer", a, services, {
        "request_id": q["id"], "claim_token": c["claim_token"], "error": "Need more context"})
    assert res["data"]["status"] == "failed"
    res = await call_tool("submit_answer", a, services, {"request_id": q["id"],
                                                         "claim_token": c["claim_token"]})
    assert res["error"]["code"] == "invalid_arguments"


# ---------------------------------------------------------------------------
# Feed integration + webhook
# ---------------------------------------------------------------------------


async def test_approved_items_become_labelled_feed_items(services, repo):
    a = principal()
    today = date(2026, 11, 25)
    it = (await call_tool("propose_feed_items", a, services, {"items": [
        item(concept_ids=["a-backprop"], target_date=today.isoformat())]}))["data"]["items"][0]
    assert await agent_feed_items(repo, USER_A, today=today) == []  # pending -> hidden
    await repo.set_feed_item_status(USER_A, it["id"], "approved")
    items = await agent_feed_items(repo, USER_A, today=today)
    assert len(items) == 1
    fi = items[0]
    assert fi.item_type == FeedItemType.AGENT_CURATED and fi.concept_id == "a-backprop"
    assert fi.content["provenance"]["curated_by"] == "agent"
    assert fi.content["source_url"].startswith("https://")
    assert await agent_feed_items(repo, USER_B, today=today) == []
    assert to_feed_item(repo.feed[it["id"]]).id == f"agent:{it['id']}"


def test_webhook_signature_roundtrip():
    body = b'{"event":"agent_request.created"}'
    header = sign_payload("s3cret", body, timestamp=1_700_000_000)
    assert verify_signature("s3cret", body, header, now=1_700_000_010)
    assert not verify_signature("wrong", body, header, now=1_700_000_010)
    assert not verify_signature("s3cret", body + b" ", header, now=1_700_000_010)
    assert not verify_signature("s3cret", body, header, now=1_700_000_000 + 3600)  # replay
    assert not verify_signature("s3cret", body, "garbage")


# ---------------------------------------------------------------------------
# MCP over streamable HTTP (real SDK, in-process ASGI)
# ---------------------------------------------------------------------------

mcp = pytest.importorskip("mcp")


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


async def test_mcp_http_auth_and_tool_call(services, repo):
    from backend.agent_bridge.mcp_app import AgentBridgeMCPApp

    async def factory():
        return services

    app = AgentBridgeMCPApp(factory)
    _, key_a = await repo.create_key(USER_A, "bot", [SCOPE_READ_KNOWLEDGE])
    _, key_b = await repo.create_key(USER_B, "bot", list(ALL))
    headers = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}

    async with app.lifespan():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            r = await client.post("/", json=_rpc("tools/list"), headers=headers)
            assert r.status_code == 401

            init = _rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "test", "version": "0"}})
            r = await client.post("/", json=init,
                                  headers={**headers, "Authorization": f"Bearer {key_a}"})
            assert r.status_code == 200, r.text

            h_a = {**headers, "Authorization": f"Bearer {key_a}"}
            r = await client.post("/", json=_rpc("tools/list", id_=2), headers=h_a)
            assert r.status_code == 200, r.text
            names = {t["name"] for t in r.json()["result"]["tools"]}
            assert {"get_knowledge_profile", "propose_feed_items", "claim_question"} <= names

            r = await client.post("/", headers=h_a, json=_rpc(
                "tools/call", {"name": "search_concepts", "arguments": {"query": "a"}}, id_=3))
            payload = json.loads(r.json()["result"]["content"][0]["text"])
            got = {c["id"] for c in payload["data"]["concepts"]}
            assert got and all(c.startswith("a-") for c in got)

            # Same server, B's key -> B's data only (no principal bleed between requests).
            h_b = {**headers, "Authorization": f"Bearer {key_b}"}
            r = await client.post("/", headers=h_b, json=_rpc(
                "tools/call", {"name": "search_concepts", "arguments": {"query": "a"}}, id_=4))
            payload = json.loads(r.json()["result"]["content"][0]["text"])
            assert all(c["id"].startswith("b-") for c in payload["data"]["concepts"])

            # A's read-only key cannot write.
            r = await client.post("/", headers=h_a, json=_rpc(
                "tools/call", {"name": "propose_feed_items", "arguments": {"items": [item()]}},
                id_=5))
            res = r.json()["result"]
            assert res.get("isError") is True
            assert json.loads(res["content"][0]["text"])["error"]["code"] == "forbidden"


# ---------------------------------------------------------------------------
# REST (app side)
# ---------------------------------------------------------------------------


def _rest_app(services, user_id):
    from fastapi import FastAPI

    from backend.agent_bridge.router import get_bridge_services, router
    from backend.auth.middleware import get_current_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id}

    async def _svc():
        return services

    app.dependency_overrides[get_bridge_services] = _svc
    return app


async def test_rest_keys_approvals_and_ask_agent(services, repo):
    app_a = _rest_app(services, USER_A)
    app_b = _rest_app(services, USER_B)
    ta = httpx.AsyncClient(transport=httpx.ASGITransport(app=app_a), base_url="http://t")
    tb = httpx.AsyncClient(transport=httpx.ASGITransport(app=app_b), base_url="http://t")
    async with ta, tb:
        default = await ta.post("/api/agent-bridge/keys", json={"name": "Read-only"})
        assert default.json()["key"]["scopes"] == ["read:knowledge"]  # least privilege by default
        r = await ta.post("/api/agent-bridge/keys", json={
            "name": "Grok Bot", "scopes": ["read:knowledge", "write:feed", "bridge:answer"]})
        assert r.status_code == 201
        body = r.json()
        assert body["api_key"].startswith("grk_") and "key_hash" not in body["key"]
        assert (await ta.post("/api/agent-bridge/keys", json={"scopes": ["root"]})).status_code == 400
        assert (await tb.delete(f"/api/agent-bridge/keys/{body['key']['id']}")).status_code == 404

        p = await authenticate_agent_key(repo, body["api_key"])
        it = (await call_tool("propose_feed_items", p, services, {"items": [item()]}))["data"]["items"][0]
        assert (await tb.post(f"/api/agent-bridge/feed-items/{it['id']}/approve")).status_code == 404
        r = await ta.get("/api/agent-bridge/feed-items")
        assert [x["id"] for x in r.json()["items"]] == [it["id"]]
        r = await ta.post(f"/api/agent-bridge/feed-items/{it['id']}/approve")
        assert r.json()["item"]["status"] == "approved"

        r = await ta.post("/api/agent-bridge/requests", json={"question": "Plan my week"})
        assert r.status_code == 202
        rid = r.json()["request"]["id"]
        assert (await tb.get(f"/api/agent-bridge/requests/{rid}")).status_code == 404

        c = (await call_tool("claim_question", p, services, {}))["data"]["question"]
        await call_tool("submit_answer", p, services, {
            "request_id": rid, "claim_token": c["claim_token"], "answer_markdown": "Do X"})
        r = await ta.get(f"/api/agent-bridge/requests/{rid}")
        assert r.json()["request"]["status"] == "answered"
        assert r.json()["request"]["answer_text"] == "Do X"

        # SSE stream terminates immediately for a finished request.
        r = await ta.get(f"/api/agent-bridge/requests/{rid}/stream")
        assert "event: status" in r.text and '"answered"' in r.text and "event: end" in r.text

        assert (await ta.delete(f"/api/agent-bridge/keys/{body['key']['id']}")).status_code == 200
        assert await authenticate_agent_key(repo, body["api_key"]) is None


# --- knowledge-map tools (feat/knowledge-map) -------------------------------------------------

def test_knowledge_map_tools_registered_with_scopes():
    from backend.agent_bridge.keys import SCOPE_READ_KNOWLEDGE, SCOPE_WRITE_FEED
    from backend.agent_bridge.tools import TOOLS

    assert TOOLS["assess_concepts"].scope == SCOPE_READ_KNOWLEDGE
    assert TOOLS["get_capability_blueprint"].scope == SCOPE_READ_KNOWLEDGE
    assert TOOLS["suggest_for_later"].scope == SCOPE_WRITE_FEED
    props = TOOLS["assess_concepts"].input_schema["properties"]
    assert "user_id" not in props and "names" in props


async def test_knowledge_profile_weak_means_reviewed_and_low():
    """Concepts never reviewed are untested, not weak: they must not crowd out real weak spots."""
    from backend.agent_bridge.knowledge import KnowledgeService

    class Neo:
        async def execute_query(self, q, params=None):
            return [{"id": f"c{i}", "name": f"Concept {i}", "domain": "ML"} for i in range(6)]

    class SR:
        async def get_due_items(self, **kw):
            return []

    svc = KnowledgeService.__new__(KnowledgeService)
    svc.neo4j, svc.sr = Neo(), SR()

    async def mastery_map(user_id):
        return {"c4": 0.2, "c5": 0.9}

    svc._mastery_map = mastery_map
    prof = await svc.get_knowledge_profile("u", limit=10)
    assert [c["id"] for c in prof["weak_concepts"]] == ["c4"]
    assert [c["id"] for c in prof["strong_concepts"]] == ["c5"]
    assert prof["reviewed_concepts"] == 2
    assert prof["domains"] == [{"domain": "ML", "concepts": 6, "untested": 4, "avg_mastery": 0.55}]
