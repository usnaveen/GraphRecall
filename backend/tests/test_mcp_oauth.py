"""Tests for MCP OAuth 2.1 + PKCE (S256) + Dynamic Client Registration + ToolAnnotations."""

from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI, Request

from backend.agent_bridge.mcp_app import AgentBridgeMCPApp, _tool_list
from backend.agent_bridge.oauth import (
    InMemoryOAuthStore,
    get_oauth_bridge_services,
    get_oauth_store,
    router as oauth_router,
)
from backend.agent_bridge.knowledge import KnowledgeService
from backend.agent_bridge.repository import InMemoryBridgeRepository
from backend.agent_bridge.tools import BridgeServices
from backend.tests.agent_bridge_fakes import USER_A, FakeNeo4j, FakePG


def _pkce_pair(verifier: str = "v" * 64) -> tuple[str, str]:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _build_test_app(monkeypatch: pytest.MonkeyPatch):
    repo = InMemoryBridgeRepository()
    knowledge = KnowledgeService(FakePG(), FakeNeo4j())
    svc = BridgeServices(repo=repo, knowledge=knowledge)
    store = InMemoryOAuthStore()

    async def fake_resolve_user(request: Request, bearer_token: str = ""):
        tok = bearer_token or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if tok == "valid-user-session":
            return {"id": USER_A, "email": "user@example.test"}
        return None

    import backend.agent_bridge.oauth as oauth_mod

    monkeypatch.setattr(oauth_mod, "resolve_authorizing_user", fake_resolve_user)

    app = FastAPI()
    app.include_router(oauth_router)
    app.dependency_overrides[get_oauth_store] = lambda: store
    app.dependency_overrides[get_oauth_bridge_services] = lambda: svc

    async def svc_factory():
        return svc

    mcp_asgi = AgentBridgeMCPApp(
        svc_factory,
        allowed_hosts=["testserver", "127.0.0.1", "localhost"],
        allowed_origins=["https://claude.ai", "https://chatgpt.com"],
    )
    app.mount("/mcp/agent", mcp_asgi)
    return app, mcp_asgi, repo, store


@pytest.mark.asyncio
async def test_mcp_401_advertises_protected_resource_and_metadata_endpoints(monkeypatch: pytest.MonkeyPatch):
    app, mcp_asgi, _, _ = _build_test_app(monkeypatch)
    async with mcp_asgi.lifespan():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r401 = await client.post("/mcp/agent/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            assert r401.status_code == 401
            www = r401.headers.get("www-authenticate", "")
            assert 'resource_metadata="http://testserver/.well-known/oauth-protected-resource"' in www

            prm = await client.get("/.well-known/oauth-protected-resource")
            assert prm.status_code == 200
            prm_body = prm.json()
            assert prm_body["resource"] == "http://testserver/mcp/agent"
            assert "read:knowledge" in prm_body["scopes_supported"]

            asm = await client.get("/.well-known/oauth-authorization-server")
            assert asm.status_code == 200
            asm_body = asm.json()
            assert asm_body["registration_endpoint"] == "http://testserver/oauth/register"
            assert asm_body["code_challenge_methods_supported"] == ["S256"]


@pytest.mark.asyncio
async def test_dcr_rejects_unsafe_redirect_uris(monkeypatch: pytest.MonkeyPatch):
    app, _, _, _ = _build_test_app(monkeypatch)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        bad_js = await client.post(
            "/oauth/register",
            json={"client_name": "Evil", "redirect_uris": ["javascript:alert(1)"]},
        )
        assert bad_js.status_code == 400
        assert bad_js.json()["error"] == "invalid_redirect_uri"

        bad_http = await client.post(
            "/oauth/register",
            json={"client_name": "Remote HTTP", "redirect_uris": ["http://evil.example.com/cb"]},
        )
        assert bad_http.status_code == 400


@pytest.mark.asyncio
async def test_full_oauth_pkce_flow_into_mcp_call_rotation_and_revocation(monkeypatch: pytest.MonkeyPatch):
    app, mcp_asgi, repo, _ = _build_test_app(monkeypatch)
    verifier, challenge = _pkce_pair()

    async with mcp_asgi.lifespan():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Dynamic Client Registration (Claude.ai callback)
            reg = await client.post(
                "/oauth/register",
                json={
                    "client_name": "Claude",
                    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                },
            )
            assert reg.status_code == 201
            client_id = reg.json()["client_id"]

            # 2. GET /oauth/authorize -> consent HTML with signed ticket
            auth_page = await client.get(
                "/oauth/authorize",
                params={
                    "client_id": client_id,
                    "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                    "response_type": "code",
                    "scope": "read:knowledge write:feed",
                    "state": "xyz-state-123",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
            )
            assert auth_page.status_code == 200
            m = re.search(r'name="ticket"\s+value="([^"]+)"', auth_page.text)
            assert m, "Consent ticket missing from HTML"
            ticket = m.group(1)

            # 3. Approve consent with valid user session
            approve = await client.post(
                "/oauth/authorize/approve",
                data={
                    "ticket": ticket,
                    "decision": "approve",
                    "scopes": ["read:knowledge", "write:feed"],
                    "session_token": "valid-user-session",
                },
                follow_redirects=False,
            )
            assert approve.status_code == 302
            loc = urlparse(approve.headers["location"])
            qs = parse_qs(loc.query)
            assert qs["state"] == ["xyz-state-123"]
            code = qs["code"][0]

            # 4. Wrong PKCE verifier fails; single-use code is already consumed -> replay also fails!
            # Register a second code so we test both wrong verifier and clean exchange.
            bad_tok = await client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": "w" * 64,
                    "client_id": client_id,
                    "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                },
            )
            assert bad_tok.status_code == 400
            assert bad_tok.json()["error"] == "invalid_grant"

            # Issue fresh code and exchange with right verifier
            approve2 = await client.post(
                "/oauth/authorize/approve",
                data={
                    "ticket": ticket,
                    "decision": "approve",
                    "scopes": ["read:knowledge", "write:feed"],
                    "session_token": "valid-user-session",
                },
                follow_redirects=False,
            )
            code2 = parse_qs(urlparse(approve2.headers["location"]).query)["code"][0]

            tok_resp = await client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code2,
                    "code_verifier": verifier,
                    "client_id": client_id,
                    "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                },
            )
            assert tok_resp.status_code == 200
            tok = tok_resp.json()
            access_token = tok["access_token"]
            refresh_token = tok["refresh_token"]
            assert access_token.startswith("grk_")
            assert refresh_token.startswith("grr_")

            # Replay of consumed code2 must fail
            replay = await client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code2,
                    "code_verifier": verifier,
                    "client_id": client_id,
                    "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                },
            )
            assert replay.status_code == 400

            # 5. Use OAuth access_token directly against /mcp/agent (with Claude.ai Origin header!)
            mcp_res = await client.post(
                "/mcp/agent/",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Origin": "https://claude.ai",
                    "Accept": "application/json, text/event-stream",
                },
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            assert mcp_res.status_code == 200
            tools_payload = mcp_res.json()["result"]["tools"]
            assert len(tools_payload) == 13

            # Verify key appears in user's iOS-visible agent_api_keys list
            keys = await repo.list_keys(USER_A)
            assert any("OAuth · Claude" in k["name"] and k["revoked_at"] is None for k in keys)

            # 6. Rotate via refresh_token -> old access_token immediately stops working
            rot = await client.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                },
            )
            assert rot.status_code == 200
            new_access = rot.json()["access_token"]
            new_refresh = rot.json()["refresh_token"]
            assert new_access != access_token

            old_try = await client.post(
                "/mcp/agent/",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            )
            assert old_try.status_code == 401

            # 7. Revoke new_refresh -> revokes underlying agent key too
            rev = await client.post("/oauth/revoke", data={"token": new_refresh})
            assert rev.status_code == 200
            rev_try = await client.post(
                "/mcp/agent/",
                headers={"Authorization": f"Bearer {new_access}", "Accept": "application/json"},
                json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
            )
            assert rev_try.status_code == 401


def test_tool_annotations_mark_read_knowledge_readonly():
    import mcp.types as types

    tools = _tool_list(types)
    by_name = {t.name: t for t in tools}
    assess = by_name["assess_concepts"]
    propose = by_name["propose_feed_items"]
    if getattr(types, "ToolAnnotations", None) is not None:
        assert assess.annotations is not None
        dumped = assess.annotations.model_dump(by_alias=True)
        assert dumped["readOnlyHint"] is True
        assert dumped["openWorldHint"] is False
        assert propose.annotations is not None
        assert propose.annotations.model_dump(by_alias=True)["readOnlyHint"] is False
