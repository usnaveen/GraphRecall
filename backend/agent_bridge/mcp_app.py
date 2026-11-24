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
from typing import Any, Callable, Optional

import structlog

from backend.agent_bridge.auth import SlidingWindowLimiter, authenticate_agent_key
from backend.agent_bridge.keys import AgentPrincipal
from backend.agent_bridge.tools import TOOLS, BridgeServices, call_tool

logger = structlog.get_logger()

SERVER_NAME = "graphrecall-agent-bridge"
INSTRUCTIONS = (
    "GraphRecall is the user's personal knowledge graph and spaced-repetition app. "
    "Use read tools to learn what they know and what is due; propose_feed_items to add "
    "curated cards (they stay pending until the user approves); and list_pending_questions "
    "-> claim_question -> submit_answer to answer questions their in-app assistant handed off."
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


def _tool_list(types: Any) -> list:
    return [
        types.Tool(name=s.name, description=f"[{s.scope}] {s.description}",
                   inputSchema=s.input_schema)
        for s in TOOLS.values()
    ]


def build_lowlevel_server(services_factory: ServicesFactory) -> Any:
    import mcp.types as types
    from mcp.server.lowlevel import Server

    async def _run(principal: Optional[AgentPrincipal], name: str, args: Optional[dict]):
        if principal is None:  # should be impossible behind the ASGI auth wrapper
            result: dict = {"ok": False, "error": {"code": "unauthorized", "message": "No agent key"}}
        else:
            services = await services_factory()
            result = await call_tool(name, principal, services, args or {})
        text = json.dumps(result, default=str)
        return result, [types.TextContent(type="text", text=text)]

    if "on_call_tool" in inspect.signature(Server.__init__).parameters:  # mcp 2.x
        async def on_list_tools(ctx: Any, params: Any) -> Any:
            return types.ListToolsResult(tools=_tool_list(types))

        async def on_call_tool(ctx: Any, params: Any) -> Any:
            principal = _principal_from_request(ctx.request) or _current_principal.get()
            result, content = await _run(principal, params.name, params.arguments)
            return types.CallToolResult(content=content, is_error=not result.get("ok"))

        return Server(SERVER_NAME, instructions=INSTRUCTIONS,
                      on_list_tools=on_list_tools, on_call_tool=on_call_tool)

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


class AgentBridgeMCPApp:
    """ASGI app: bearer-key auth + rate limit in front of the MCP session manager."""

    def __init__(self, services_factory: ServicesFactory,
                 limiter: Optional[SlidingWindowLimiter] = None):
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

        self.services_factory = services_factory
        self.limiter = limiter or SlidingWindowLimiter()
        self.server = build_lowlevel_server(services_factory)
        # TODO(agent-bridge): configure TransportSecuritySettings (allowed hosts/origins)
        # for the public deployment hostname.
        self.session_manager = StreamableHTTPSessionManager(
            app=self.server, stateless=True, json_response=True
        )

    @contextlib.asynccontextmanager
    async def lifespan(self):
        async with self.session_manager.run():
            yield

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] == "lifespan":  # standalone uvicorn
            await self._lifespan(receive, send)
            return
        if scope["type"] != "http":
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
            await _json(send, 401, {"error": "invalid_or_missing_agent_key"},
                        extra=[(b"www-authenticate", b'Bearer realm="graphrecall-agent"')])
            return
        if not self.limiter.allow(principal.key_id):
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
    from backend.agent_bridge.repository import PostgresBridgeRepository
    from backend.agent_bridge.webhook import notifier_from_env
    from backend.db.neo4j_client import get_neo4j_client
    from backend.db.postgres_client import get_postgres_client

    class _LazyNeo4j:
        """Connect to Neo4j only when a knowledge tool actually needs it (auth and the
        queue/feed tools are Postgres-only)."""

        async def execute_query(self, query: str, parameters: Optional[dict] = None) -> list:
            return await (await get_neo4j_client()).execute_query(query, parameters)

    pg = await get_postgres_client()
    return BridgeServices(repo=PostgresBridgeRepository(pg),
                          knowledge=KnowledgeService(pg, _LazyNeo4j()),
                          notifier=notifier_from_env())


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover - manual entrypoint
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
    uvicorn.run(AgentBridgeMCPApp(default_services), host=a.host, port=a.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
