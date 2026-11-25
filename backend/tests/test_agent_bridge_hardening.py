"""Agent bridge hardening (PR #3 review): terminal question states, URL validation,
malformed ids, feed limits/filters, key limits, feed state machine, pepper fail-closed,
enqueue rate limit, background webhook with bounded retry."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from backend.agent_bridge import keys as keys_mod
from backend.agent_bridge import router as router_mod
from backend.agent_bridge.auth import authenticate_agent_key
from backend.agent_bridge.dedupe import is_safe_http_url
from backend.agent_bridge.feed_integration import filter_by_domains, merge_into_feed, to_feed_item
from backend.agent_bridge.jobs import sweep_stale_requests
from backend.agent_bridge.keys import (
    SCOPE_BRIDGE_ANSWER,
    SCOPE_READ_KNOWLEDGE,
    SCOPE_WRITE_FEED,
    AgentPrincipal,
    KeyConfigError,
)
from backend.agent_bridge.knowledge import KnowledgeService
from backend.agent_bridge.repository import InMemoryBridgeRepository, InvalidTransitionError
from backend.agent_bridge.tools import BridgeServices, call_tool
from backend.agent_bridge.webhook import WebhookNotifier, dispatch_in_background, verify_signature
from backend.tests.agent_bridge_fakes import USER_A, USER_B, FakeNeo4j, FakePG

ALL = frozenset({SCOPE_READ_KNOWLEDGE, SCOPE_WRITE_FEED, SCOPE_BRIDGE_ANSWER})
PAST = lambda s=1: datetime.now(timezone.utc) - timedelta(seconds=s)  # noqa: E731


@pytest.fixture
def repo():
    return InMemoryBridgeRepository()


@pytest.fixture
def services(repo):
    return BridgeServices(repo=repo, knowledge=KnowledgeService(FakePG(), FakeNeo4j()))




def principal(user=USER_A, key_id="key-a"):
    return AgentPrincipal(user_id=user, key_id=key_id, scopes=ALL)


def item(**kw):
    base = {"title": "Card", "summary": "Summary", "reason": "Reason",
            "source_url": "https://example.com/a", "target_date": "2026-11-25"}
    base.update(kw)
    return base


def rest_client(services, user_id):
    from fastapi import FastAPI

    from backend.auth.middleware import get_current_user

    app = FastAPI()
    app.include_router(router_mod.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id}

    async def _svc():
        return services

    app.dependency_overrides[router_mod.get_bridge_services] = _svc
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


# ---------------------------------------------------------------------------
# 1. Questions reach terminal states
# ---------------------------------------------------------------------------


async def test_past_deadline_question_becomes_expired(services, repo):
    q = await repo.enqueue_request(USER_A, "late")
    repo.requests[q["id"]]["expires_at"] = PAST()
    listed = (await call_tool("list_pending_questions", principal(), services, {}))["data"]
    assert listed["questions"] == []
    row = await repo.get_request(USER_A, q["id"])
    assert row["status"] == "expired" and "Deadline" in row["error"]
    assert (await call_tool("claim_question", principal(), services, {}))["data"]["claimed"] is False


async def test_exhausted_attempts_become_failed(services, repo):
    q = await repo.enqueue_request(USER_A, "hard")
    for _ in range(3):
        c = await repo.claim_request(USER_A, "k")
        assert c
        repo.requests[q["id"]]["lease_expires_at"] = PAST()
    # Third lease lapsed with attempts == 3 -> failed, not "claimed" forever.
    listed = (await call_tool("list_pending_questions", principal(), services, {}))["data"]
    assert listed["questions"] == []
    row = await repo.get_request(USER_A, q["id"])
    assert row["status"] == "failed" and "3 attempts" in row["error"]
    assert row["claim_token"] is None


async def test_last_attempt_in_progress_is_listed_but_not_claimable(services, repo):
    q = await repo.enqueue_request(USER_A, "q")
    for i in range(3):
        await repo.claim_request(USER_A, "k")
        if i < 2:
            repo.requests[q["id"]]["lease_expires_at"] = PAST()
    listed = (await call_tool("list_pending_questions", principal(), services, {}))["data"]
    assert [x["claimable"] for x in listed["questions"]] == [False]


async def test_deadline_does_not_cut_a_live_lease(repo):
    q = await repo.enqueue_request(USER_A, "q")
    c = await repo.claim_request(USER_A, "k", lease_seconds=600)
    repo.requests[q["id"]]["expires_at"] = PAST()
    assert (await repo.get_request(USER_A, q["id"]))["status"] == "claimed"
    done = await repo.complete_request(USER_A, q["id"], c["claim_token"], answer_text="ok")
    assert done["status"] == "answered"


async def test_sweep_job_is_global_and_counts(repo):
    qa = await repo.enqueue_request(USER_A, "a")
    qb = await repo.enqueue_request(USER_B, "b")
    repo.requests[qa["id"]]["expires_at"] = PAST()
    for _ in range(3):
        await repo.claim_request(USER_B, "kb")
        repo.requests[qb["id"]]["lease_expires_at"] = PAST()
    live = await repo.enqueue_request(USER_A, "fresh")
    # Inspect raw rows (no lazy sweep) to prove the job does the work.
    assert repo.requests[qa["id"]]["status"] == "queued"
    assert await sweep_stale_requests(repo) == {"expired": 1, "failed": 1}
    assert repo.requests[qa["id"]]["status"] == "expired"
    assert repo.requests[qb["id"]]["status"] == "failed"
    assert repo.requests[live["id"]]["status"] == "queued"
    assert await sweep_stale_requests(repo) == {"expired": 0, "failed": 0}


@pytest.mark.parametrize("make_terminal,expected", [
    ("expire", "expired"), ("exhaust", "failed"), ("cancel", "cancelled")])
async def test_status_stream_surfaces_terminal_states(services, repo, make_terminal, expected):
    q = await repo.enqueue_request(USER_A, "q")
    if make_terminal == "expire":
        repo.requests[q["id"]]["expires_at"] = PAST()
    elif make_terminal == "exhaust":
        for _ in range(3):
            await repo.claim_request(USER_A, "k")
            repo.requests[q["id"]]["lease_expires_at"] = PAST()
    else:
        await repo.cancel_request(USER_A, q["id"])
    async with rest_client(services, USER_A) as c:
        r = await asyncio.wait_for(c.get(f"/api/agent-bridge/requests/{q['id']}/stream"), 5)
        assert f'"status": "{expected}"' in r.text
        end = r.text.split("event: end\ndata: ", 1)[1].strip()
        assert json.loads(end) == {"status": expected, "terminal": True}
        r = await c.get(f"/api/agent-bridge/requests?status={expected}")
        assert [x["id"] for x in r.json()["requests"]] == [q["id"]]


# ---------------------------------------------------------------------------
# 2. URL validation
# ---------------------------------------------------------------------------

BAD_URLS = ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<script>x</script>",
            "vbscript:msgbox", "file:///etc/passwd", "//evil.example/x", "https://",
            "https://exa mple.com", "http:\\\\evil.example", "mailto:a@b.c", " javascript:x"]


@pytest.mark.parametrize("url", BAD_URLS)
def test_is_safe_http_url_rejects(url):
    assert is_safe_http_url(url) is False


def test_is_safe_http_url_accepts():
    assert is_safe_http_url("https://example.com/a?b=1#c")
    assert is_safe_http_url("http://localhost:8000/x")


@pytest.mark.parametrize("url", BAD_URLS[:5])
async def test_citation_urls_must_be_http(services, repo, url):
    q = await repo.enqueue_request(USER_A, "q")
    c = (await call_tool("claim_question", principal(), services, {}))["data"]["question"]
    res = await call_tool("submit_answer", principal(), services, {
        "request_id": q["id"], "claim_token": c["claim_token"], "answer_markdown": "x",
        "citations": [{"title": "t", "url": url}]})
    assert res["ok"] is False and res["error"]["code"] == "invalid_arguments"
    assert (await repo.get_request(USER_A, q["id"]))["status"] == "claimed"
    ok = await call_tool("submit_answer", principal(), services, {
        "request_id": q["id"], "claim_token": c["claim_token"], "answer_markdown": "x",
        "citations": [{"title": "t", "url": "https://ok.example"}, {"title": "no url"}]})
    assert ok["ok"] is True


@pytest.mark.parametrize("url", BAD_URLS[:6])
async def test_feed_source_url_must_be_http(services, url):
    res = await call_tool("propose_feed_items", principal(), services,
                          {"items": [item(source_url=url)]})
    assert res["ok"] is False and res["error"]["code"] == "invalid_arguments"


# ---------------------------------------------------------------------------
# 3. Malformed ids, feed limits, key limits, state machine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool,args", [
    ("claim_question", {"request_id": "not-a-uuid"}),
    ("submit_answer", {"request_id": "x", "claim_token": "y", "answer_markdown": "a"}),
    ("submit_answer", {"request_id": "6f1c0c55-1111-4b7a-9a59-000000000000",
                       "claim_token": "'; drop table--", "answer_markdown": "a"}),
    ("schedule_daily_digest", {"title": "t", "item_ids": ["nope"]}),
])
async def test_malformed_ids_are_invalid_arguments_not_internal(services, tool, args):
    res = await call_tool(tool, principal(), services, args)
    assert res["ok"] is False and res["error"]["code"] == "invalid_arguments"


async def test_rest_malformed_ids_return_400(services):
    async with rest_client(services, USER_A) as c:
        for method, path in [("get", "/api/agent-bridge/requests/abc"),
                             ("get", "/api/agent-bridge/requests/abc/stream"),
                             ("post", "/api/agent-bridge/requests/abc/cancel"),
                             ("post", "/api/agent-bridge/feed-items/abc/approve"),
                             ("post", "/api/agent-bridge/feed-items/abc/reject"),
                             ("delete", "/api/agent-bridge/keys/abc")]:
            r = await getattr(c, method)(path)
            assert r.status_code == 400, (path, r.status_code)
        r = await c.post("/api/agent-bridge/requests",
                         json={"question": "q", "conversation_id": "zzz"})
        assert r.status_code == 400
        assert (await c.get("/api/agent-bridge/requests?status=bogus")).status_code == 400
        # Well-formed but unknown -> 404.
        r = await c.get("/api/agent-bridge/requests/6f1c0c55-1111-4b7a-9a59-000000000000")
        assert r.status_code == 404


async def test_repo_tolerates_malformed_ids(repo):
    assert await repo.get_request(USER_A, "bad") is None
    assert await repo.cancel_request(USER_A, "bad") is None
    assert await repo.claim_request(USER_A, "k", request_id="bad") is None
    assert await repo.set_feed_item_status(USER_A, "bad", "approved") is None


def _fi(n, cids=None):
    return to_feed_item({"id": f"00000000-0000-0000-0000-00000000000{n}", "title": f"t{n}",
                         "summary": "s", "reason": "r", "concept_ids": cids or [],
                         "target_date": date(2026, 11, 25)})


def test_merge_respects_max_items():
    curated = [_fi(i) for i in range(5)]
    base = [f"base{i}" for i in range(20)]
    for max_items in (1, 2, 3, 10, 20, 50):
        merged = merge_into_feed(curated, base[:max_items], max_items)
        assert len(merged) <= max_items
        assert sum(1 for m in merged if not isinstance(m, str)) >= 1
    assert merge_into_feed(curated, [], 3) == curated[:1]
    assert merge_into_feed(curated, base[:20], 20)[:5] == curated
    assert merge_into_feed(curated, base, 0) == []


async def test_domain_filter_on_agent_cards():
    neo = FakeNeo4j()
    cards = [_fi(1, ["a-backprop"]), _fi(2, []), _fi(3, ["b-sql"]), _fi(4, ["a-gd", "a-x"])]
    kept = await filter_by_domains(neo, USER_A, cards, ["Machine Learning"])
    assert [k.content["title"] for k in kept] == ["t1", "t4"]  # untagged + foreign dropped
    assert await filter_by_domains(neo, USER_A, cards, None) == cards
    assert await filter_by_domains(neo, USER_A, cards, ["Database Systems"]) == []


async def test_expired_and_revoked_keys_do_not_count_toward_limit(services, repo):
    for i in range(3):
        await repo.create_key(USER_A, f"old{i}", ["read:knowledge"], expires_at=PAST())
    r0, _ = await repo.create_key(USER_A, "revoked", ["read:knowledge"])
    await repo.revoke_key(USER_A, r0["id"])
    async with rest_client(services, USER_A) as c:
        for i in range(router_mod.MAX_KEYS_PER_USER):
            assert (await c.post("/api/agent-bridge/keys", json={"name": f"k{i}"})).status_code == 201
        assert (await c.post("/api/agent-bridge/keys", json={"name": "extra"})).status_code == 409


async def test_feed_state_machine(services, repo):
    a = principal()
    ids = [x["id"] for x in (await call_tool("propose_feed_items", a, services, {"items": [
        item(source_url="https://e.com/1"), item(source_url="https://e.com/2")]}))["data"]["items"]]
    async with rest_client(services, USER_A) as c:
        assert (await c.post(f"/api/agent-bridge/feed-items/{ids[0]}/reject")).status_code == 200
        r = await c.post(f"/api/agent-bridge/feed-items/{ids[0]}/approve")
        assert r.status_code == 409 and "rejected" in r.json()["detail"]
        assert repo.feed[ids[0]]["status"] == "rejected"
        assert (await c.post(f"/api/agent-bridge/feed-items/{ids[0]}/reject")).status_code == 200
        # approve is idempotent; an approved card may later be hidden.
        assert (await c.post(f"/api/agent-bridge/feed-items/{ids[1]}/approve")).status_code == 200
        first_reviewed = repo.feed[ids[1]]["reviewed_at"]
        assert (await c.post(f"/api/agent-bridge/feed-items/{ids[1]}/approve")).status_code == 200
        assert repo.feed[ids[1]]["reviewed_at"] == first_reviewed
        assert (await c.post(f"/api/agent-bridge/feed-items/{ids[1]}/reject")).status_code == 200
    with pytest.raises(InvalidTransitionError):
        await repo.set_feed_item_status(USER_A, ids[1], "approved")


# ---------------------------------------------------------------------------
# 4. Pepper, enqueue rate limit, background webhook
# ---------------------------------------------------------------------------


async def test_pepper_fails_closed_in_production(monkeypatch, repo, services):
    _, key = await repo.create_key(USER_A, "bot", ["read:knowledge"])  # dev, no pepper
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("AGENT_KEY_PEPPER", raising=False)
    with pytest.raises(KeyConfigError):
        keys_mod.check_key_config()
    with pytest.raises(KeyConfigError):
        keys_mod.generate_key()
    assert await authenticate_agent_key(repo, key) is None  # nobody authenticates
    async with rest_client(services, USER_A) as c:
        assert (await c.post("/api/agent-bridge/keys", json={})).status_code == 503
    monkeypatch.setenv("AGENT_KEY_PEPPER", "pep")
    keys_mod.check_key_config()
    _, key2 = await repo.create_key(USER_A, "bot2", ["read:knowledge"])
    assert (await authenticate_agent_key(repo, key2)).user_id == USER_A


def test_pepper_warns_in_dev(monkeypatch, caplog):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("AGENT_KEY_PEPPER", raising=False)
    monkeypatch.setattr(keys_mod, "_warned_no_pepper", False)
    with caplog.at_level("WARNING"):
        keys_mod.check_key_config()
    assert "AGENT_KEY_PEPPER is not set" in caplog.text


async def test_enqueue_is_rate_limited_per_user(monkeypatch, services):
    monkeypatch.setenv("AGENT_BRIDGE_ENQUEUE_PER_HOUR", "3")
    async with rest_client(services, USER_A) as a, rest_client(services, USER_B) as b:
        codes = [(await a.post("/api/agent-bridge/requests", json={"question": f"q{i}"})).status_code
                 for i in range(4)]
        assert codes == [202, 202, 202, 429]
        assert (await b.post("/api/agent-bridge/requests", json={"question": "q"})).status_code == 202


class SlowNotifier:
    def __init__(self):
        self.calls = []
        self.done = asyncio.Event()

    async def notify(self, user_id, event, data):
        await asyncio.sleep(1.5)
        self.calls.append((user_id, event, data))
        self.done.set()


async def test_enqueue_does_not_wait_for_webhook(repo):
    notifier = SlowNotifier()
    svc = BridgeServices(repo=repo, knowledge=KnowledgeService(FakePG(), FakeNeo4j()),
                         notifier=notifier)
    async with rest_client(svc, USER_A) as c:
        t0 = time.monotonic()
        r = await c.post("/api/agent-bridge/requests", json={"question": "q"})
        elapsed = time.monotonic() - t0
    assert r.status_code == 202 and elapsed < 1.0, elapsed
    await asyncio.wait_for(notifier.done.wait(), 5)
    assert notifier.calls[0][1] == "agent_request.created"
    assert notifier.calls[0][2]["request_id"] == r.json()["request"]["id"]


def _transport(statuses, seen):
    it = iter(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        st = next(it)
        if st == "boom":
            raise httpx.ConnectError("down")
        return httpx.Response(st)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("statuses,ok,attempts", [
    ([200], True, 1),
    ([500, "boom", 204], True, 3),
    ([429, 200], True, 2),
    ([400], False, 1),
    ([503, 503, 503], False, 3),
])
async def test_webhook_bounded_retry(statuses, ok, attempts):
    seen: list = []
    n = WebhookNotifier("https://hook.example/x", "sec", max_attempts=3, backoff_seconds=0,
                        transport=_transport(statuses, seen))
    assert await n.notify(USER_A, "agent_request.created", {"request_id": "r"}) is ok
    assert n.last_attempts == attempts == len(seen)
    for req in seen:
        assert verify_signature("sec", req.content, req.headers["X-GraphRecall-Signature"])
        assert b"question" not in req.content  # ids only


async def test_dispatch_in_background_returns_immediately():
    notifier = SlowNotifier()
    t0 = time.monotonic()
    task = dispatch_in_background(notifier, USER_A, "e", {})
    assert time.monotonic() - t0 < 0.1 and task is not None
    await asyncio.wait_for(task, 5)
    assert notifier.calls


async def test_default_worker_builds_and_community_recompute_exists():
    """The always-on worker must start: it crashed on CommunityService(pg, neo4j) and called a
    recompute_communities method that did not exist (found running it locally, 26 Nov)."""
    from unittest.mock import AsyncMock, patch

    from backend.agent_v2 import worker as w
    from backend.services.community_service import CommunityService

    assert callable(getattr(CommunityService(), "recompute_communities", None))
    with patch("backend.db.postgres_client.get_postgres_client", AsyncMock(return_value=object())), \
         patch("backend.db.neo4j_client.get_neo4j_client", AsyncMock(return_value=object())):
        try:
            built = await w.build_default_worker()
        except TypeError as e:  # constructor mismatches are what this test guards
            raise AssertionError(f"worker failed to build: {e}")
        except Exception:
            return  # other environment dependencies (Gemini key etc.) are out of scope here
    assert "article.digest" in built._handlers and "community.recompute" in built._handlers
