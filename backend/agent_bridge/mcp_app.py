"""MCP server for the agent bridge (streamable HTTP).

Mount inside FastAPI (``AGENT_BRIDGE_ENABLED=1`` -> ``/mcp/agent``) or run standalone::

    python -m backend.agent_bridge.mcp_app --port 8100

Auth: ``Authorization: Bearer grk_<prefix>_<secret>`` (an agent key created in the app
via ``POST /api/agent-bridge/keys``). The key's owner is the only user every tool can
see or write. Transport is stateless + JSON responses so each HTTP request is
authenticated on its own and no session state is shared across callers.

Works with the official ``mcp`` SDK 2.x (``on_list_tools``/``on_call_tool`` callbacks)
and 1.x (decorators).
"""

from __future__ import annotations

import contextlib
import contextvars
import inspect
import json
import os
from typing import Any, Callable, Optional

import structlog

from pydantic import BaseModel

from backend.agent_bridge import bridge_enabled, limits
from backend.agent_bridge import skills as skills_mod
from backend.agent_bridge.auth import authenticate_agent_key
from backend.agent_bridge.limits import RateLimiter
from backend.agent_bridge.serialization import to_jsonable
from backend.agent_bridge.keys import AgentPrincipal
from backend.agent_bridge.tools import TOOLS, BridgeServices, call_tool

logger = structlog.get_logger()

SERVER_NAME = "graphrecall-agent-bridge"
INSTRUCTIONS = (
    "GraphRecall is the user's personal knowledge graph and spaced-repetition app. "
    "Use read tools to learn what they know and what is due; propose_feed_items to add "
    "curated cards (they stay pending until the user approves); and list_pending_questions "
    "-> claim_question -> submit_answer to answer questions their in-app assistant handed off. "
    "Search these tools whenever the user asks you to explain or teach something (to pitch it at "
    "what they know), to quiz or review them, or to find reading for them. Skills on this server "
    "(teach-at-my-level, quiz-due-reviews, answer-app-questions, curate-my-feed) give the full steps."
)

_current_principal: contextvars.ContextVar[Optional[AgentPrincipal]] = contextvars.ContextVar(
    "agent_bridge_principal", default=None
)

ServicesFactory = Callable[[], Any]  # async () -> BridgeServices


def _principal_from_request(request: Any) -> Optional[AgentPrincipal]:
    try:
        return request.scope.get("state", {}).get("agent_principal")  # type: ignore[union-attr]
    except AttributeError:
        return None


def _tool_annotations(types: Any, scope: str) -> Any:
    """MCP ToolAnnotations so ChatGPT/Claude connectors recognize read-only knowledge lookups."""
    ann_cls = getattr(types, "ToolAnnotations", None)
    if ann_cls is None:  # pragma: no cover - older SDK fallback
        return None
    is_read = scope == "read:knowledge"
    return ann_cls(
        readOnlyHint=is_read,
        destructiveHint=False,
        idempotentHint=is_read,
        openWorldHint=False,
    )


def _tool_list(types: Any) -> list:
    out = []
    for s in TOOLS.values():
        kwargs: dict[str, Any] = {
            "name": s.name,
            "description": f"[{s.scope}] {s.description}",
            "inputSchema": s.input_schema,
        }
        ann = _tool_annotations(types, s.scope)
        if ann is not None:
            kwargs["annotations"] = ann
        out.append(types.Tool(**kwargs))
    return out


def _ctx_scopes(ctx: Any) -> frozenset[str]:
    principal = _principal_from_request(getattr(ctx, "request", None)) or _current_principal.get()
    return frozenset(principal.scopes) if principal is not None else frozenset()


def _invalid(uri: str) -> Exception:
    from mcp.shared.exceptions import MCPError

    return MCPError(-32602, f"Unknown resource: {uri}")


def _skill_resources_list(types: Any) -> Callable:
    """resources/list: the SKILL.md of each skill this key can run (skills are the only resources)."""
    async def on_list_resources(ctx: Any, params: Any) -> Any:
        return types.ListResourcesResult(resources=[
            types.Resource(uri=s.uri, name=s.name, description=s.frontmatter.get("description"),
                           mimeType="text/markdown")
            for s in skills_mod.visible(_ctx_scopes(ctx))])
    return on_list_resources


def _skill_resource_read(types: Any) -> Callable:
    async def on_read_resource(ctx: Any, params: Any) -> Any:
        uri = str(params.uri)
        try:
            text, mime = skills_mod.read_file(uri, _ctx_scopes(ctx))
        except skills_mod.SkillNotFound:
            raise _invalid(uri)
        return types.ReadResourceResult(contents=[types.TextResourceContents(uri=uri, mimeType=mime, text=text)])
    return on_read_resource


class _SkillGetParams(BaseModel):
    model_config = {"extra": "allow"}
    uri: str


def add_skills_extension(server: Any, types: Any) -> None:
    """Advertise io.modelcontextprotocol/skills and serve skills/list + skills/get (mcp 2.x lowlevel)."""
    async def skills_list(ctx: Any, params: Any) -> dict:
        return skills_mod.list_result(_ctx_scopes(ctx))

    async def skills_get(ctx: Any, params: Any) -> dict:
        try:
            return skills_mod.get_result(params.uri, _ctx_scopes(ctx))
        except skills_mod.SkillNotFound:
            raise _invalid(params.uri)

    server.add_request_handler("skills/list", types.PaginatedRequestParams, skills_list)
    server.add_request_handler("skills/get", _SkillGetParams, skills_get)
    server.extensions[skills_mod.EXTENSION_ID] = {}


def build_lowlevel_server(services_factory: ServicesFactory) -> Any:
    import mcp.types as types
    from mcp.server.lowlevel import Server

    async def _run(principal: Optional[AgentPrincipal], name: str, args: Optional[dict]):
        if principal is None:  # should be impossible behind the ASGI auth wrapper
            result: dict = {"ok": False, "error": {"code": "unauthorized", "message": "No agent key"}}
        else:
            services = await services_factory()
            result = await call_tool(name, principal, services, args or {})
        text = json.dumps(to_jsonable(result))
        return result, [types.TextContent(type="text", text=text)]

    if "on_call_tool" in inspect.signature(Server.__init__).parameters:  # mcp 2.x
        async def on_list_tools(ctx: Any, params: Any) -> Any:
            return types.ListToolsResult(tools=_tool_list(types))

        async def on_call_tool(ctx: Any, params: Any) -> Any:
            principal = _principal_from_request(ctx.request) or _current_principal.get()
            result, content = await _run(principal, params.name, params.arguments)
            return types.CallToolResult(content=content, is_error=not result.get("ok"))

        server = Server(SERVER_NAME, instructions=INSTRUCTIONS,
                        on_list_tools=on_list_tools, on_call_tool=on_call_tool,
                        on_list_resources=_skill_resources_list(types),
                        on_read_resource=_skill_resource_read(types))
        add_skills_extension(server, types)
        return server

    # mcp 1.x
    server = Server(SERVER_NAME, instructions=INSTRUCTIONS)  # pragma: no cover

    @server.list_tools()  # pragma: no cover
    async def _list() -> list:
        return _tool_list(types)

    @server.call_tool()  # pragma: no cover
    async def _call(name: str, arguments: Optional[dict]) -> Any:
        req = getattr(server.request_context, "request", None)
        principal = _principal_from_request(req) or _current_principal.get()
        result, content = await _run(principal, name, arguments)
        # Recent 1.x releases accept a CallToolResult so isError can be set.
        return types.CallToolResult(content=content, isError=not result.get("ok"))

    return server  # pragma: no cover


DEFAULT_ALLOWED_HOSTS = ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]:*"]


def _split_env(name: str) -> list[str]:
    return [h.strip() for h in os.environ.get(name, "").split(",") if h.strip()]


def allowed_hosts_from_env() -> list[str]:
    """``AGENT_BRIDGE_ALLOWED_HOSTS`` (comma list, ``host`` or ``host:*``) plus Render's
    ``RENDER_EXTERNAL_HOSTNAME`` when present, plus localhost for dev."""
    hosts = list(DEFAULT_ALLOWED_HOSTS) + _split_env("AGENT_BRIDGE_ALLOWED_HOSTS")
    render = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if render:
        hosts.append(render)
    return hosts


DEFAULT_OAUTH_WEB_ORIGINS = [
    "https://claude.ai",
    "https://chatgpt.com",
    "https://chat.openai.com",
]


def allowed_origins_from_env() -> list[str]:
    env_origins = _split_env("AGENT_BRIDGE_ALLOWED_ORIGINS")
    return list(dict.fromkeys(DEFAULT_OAUTH_WEB_ORIGINS + env_origins))


def host_allowed(host: Optional[str], allowed: list[str]) -> bool:
    if not host:
        return False
    host = host.strip().lower()
    for pat in allowed:
        pat = pat.lower()
        if pat == host:
            return True
        if pat.endswith(":*") and host.rsplit(":", 1)[0] == pat[:-2] and ":" in host:
            return True
    return False


class AgentBridgeMCPApp:
    """ASGI app: host/origin allowlist (DNS-rebinding guard) + bearer-key auth + rate limit
    in front of the MCP session manager."""

    def __init__(self, services_factory: ServicesFactory,
                 limiter: Optional[RateLimiter] = None,
                 allowed_hosts: Optional[list[str]] = None,
                 allowed_origins: Optional[list[str]] = None):
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

        self.services_factory = services_factory
        self.limiter = limiter  # None -> use services.limiter
        self.allowed_hosts = allowed_hosts if allowed_hosts is not None else allowed_hosts_from_env()
        self.allowed_origins = (allowed_origins if allowed_origins is not None
                                else allowed_origins_from_env())
        self.server = build_lowlevel_server(services_factory)
        kwargs: dict[str, Any] = {}
        try:  # SDK-level DNS-rebinding protection too (same lists), when available
            from mcp.server.transport_security import TransportSecuritySettings

            kwargs["security_settings"] = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=self.allowed_hosts,
                allowed_origins=self.allowed_origins,
            )
        except ImportError:  # pragma: no cover - very old SDKs
            pass
        self.session_manager = StreamableHTTPSessionManager(
            app=self.server, stateless=True, json_response=True, **kwargs
        )

    @contextlib.asynccontextmanager
    async def lifespan(self):
        async with self.session_manager.run():
            yield

    def _check_host_origin(self, scope: dict) -> Optional[str]:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        if not host_allowed(headers.get("host"), self.allowed_hosts):
            return "host_not_allowed"
        origin = headers.get("origin")
        # Server-side MCP clients send no Origin; browsers always do -> must be allowlisted.
        if origin is not None and origin not in self.allowed_origins:
            return "origin_not_allowed"
        return None

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] == "lifespan":  # standalone uvicorn
            await self._lifespan(receive, send)
            return
        if scope["type"] != "http":
            return
        denied = self._check_host_origin(scope)
        if denied:
            await _json(send, 421 if denied == "host_not_allowed" else 403, {"error": denied})
            return
        token = None
        for k, v in scope.get("headers", []):
            if k == b"authorization":
                val = v.decode("latin-1")
                if val.lower().startswith("bearer "):
                    token = val[7:].strip()
        services = await self.services_factory()
        principal = await authenticate_agent_key(services.repo, token)
        if principal is None:
            from backend.agent_bridge.oauth import base_url_from_asgi_scope

            base = base_url_from_asgi_scope(scope)
            www_auth = (
                f'Bearer realm="graphrecall-agent", '
                f'resource_metadata="{base}/.well-known/oauth-protected-resource"'
            ).encode("latin-1")
            await _json(send, 401, {"error": "invalid_or_missing_agent_key"},
                        extra=[(b"www-authenticate", www_auth)])
            return
        limiter = self.limiter or services.limiter
        if not await limiter.hit(f"mcp:key:{principal.key_id}", limits.mcp_calls_per_min(), 60):
            await _json(send, 429, {"error": "rate_limited"}, extra=[(b"retry-after", b"60")])
            return
        scope.setdefault("state", {})["agent_principal"] = principal
        token_ctx = _current_principal.set(principal)
        try:
            await self.session_manager.handle_request(scope, receive, send)
        finally:
            _current_principal.reset(token_ctx)

    async def _lifespan(self, receive: Callable, send: Callable) -> None:
        stack = contextlib.AsyncExitStack()
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                await stack.enter_async_context(self.lifespan())
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                await stack.aclose()
                await send({"type": "lifespan.shutdown.complete"})
                return


async def _json(send: Callable, status: int, body: dict, extra: Optional[list] = None) -> None:
    raw = json.dumps(body).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers + (extra or [])})
    await send({"type": "http.response.body", "body": raw})


async def default_services() -> BridgeServices:
    """Production wiring: shared Postgres/Neo4j clients used by the rest of the API."""
    from backend.agent_bridge.knowledge import KnowledgeService
    from backend.agent_bridge.limits import limiter_from_env
    from backend.agent_bridge.repository import PostgresBridgeRepository
    from backend.agent_bridge.webhook import notifier_from_env
    from backend.db.neo4j_client import get_neo4j_client
    from backend.db.postgres_client import get_postgres_client
    from backend.services.concept_similarity import similar_to_text

    class _LazyNeo4j:
        """Connect to Neo4j only when a knowledge tool actually needs it (auth and the
        queue/feed tools are Postgres-only)."""

        async def execute_query(self, query: str, parameters: Optional[dict] = None) -> list:
            return await (await get_neo4j_client()).execute_query(query, parameters)

    pg = await get_postgres_client()
    return BridgeServices(repo=PostgresBridgeRepository(pg),
                          knowledge=KnowledgeService(pg, _LazyNeo4j(), similar=similar_to_text),
                          notifier=notifier_from_env(), limiter=limiter_from_env(pg))


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="GraphRecall agent-bridge MCP server (HTTP)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--list-tools", action="store_true")
    a = ap.parse_args(argv)
    if a.list_tools:
        print(json.dumps([{"name": s.name, "scope": s.scope, "description": s.description}
                          for s in TOOLS.values()], indent=2))
        return 0
    if not bridge_enabled():
        print("Refusing to start: set AGENT_BRIDGE_ENABLED=1 to serve the agent-bridge MCP app.",
              file=__import__("sys").stderr)
        return 2
    from backend.agent_bridge.keys import check_key_config

    check_key_config()
    uvicorn.run(AgentBridgeMCPApp(default_services), host=a.host, port=a.port)  # pragma: no cover
    return 0  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
