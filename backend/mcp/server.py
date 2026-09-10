"""GraphRecall MCP stdio server (NAV-28).

Entrypoint:
  python -m backend.mcp.server

Uses the official `mcp` Python SDK when installed; otherwise runs a clear
stub that prints the tool→route map and exits (or --self-check against API).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from backend.mcp.tools import (
    TOOL_DEFS,
    api_base,
    api_token,
    dispatch_tool,
    result_as_text,
    tool_route_map,
)


def _mcp_available() -> bool:
    try:
        import mcp  # noqa: F401
        from mcp.server import Server  # noqa: F401
        from mcp.server.stdio import stdio_server  # noqa: F401

        return True
    except ImportError:
        return False


async def _run_mcp_stdio() -> None:
    """Official MCP SDK stdio loop."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    import mcp.types as types

    app = Server("graphrecall")

    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        tools: list[types.Tool] = []
        for t in TOOL_DEFS:
            tools.append(
                types.Tool(
                    name=t["name"],
                    description=t.get("description", ""),
                    inputSchema=t.get("inputSchema") or {"type": "object"},
                )
            )
        return tools

    @app.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        result = await asyncio.to_thread(dispatch_tool, name, arguments or {})
        text = result_as_text(result)
        return [types.TextContent(type="text", text=text)]

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


def _print_stub_banner() -> None:
    print("GraphRecall MCP server (NAV-28) — stub / docs mode", file=sys.stderr)
    print(f"  GRAPHRECALL_API_BASE  = {api_base()}", file=sys.stderr)
    token = api_token()
    print(
        f"  GRAPHRECALL_API_TOKEN = {'(set)' if token else '(not set)'}",
        file=sys.stderr,
    )
    print("  Tool → route map:", file=sys.stderr)
    for name, route in tool_route_map().items():
        print(f"    {name:24} {route}", file=sys.stderr)
    print(
        "  Install SDK: pip install 'mcp>=1.0.0'  (also in requirements.txt)",
        file=sys.stderr,
    )
    print(
        "  Then: python -m backend.mcp.server   # stdio MCP for Cursor",
        file=sys.stderr,
    )


def _self_check() -> int:
    """Probe API with safe GET tools; always print JSON (graceful if API down)."""
    print(json.dumps({"base": api_base(), "token_set": bool(api_token())}, indent=2))
    graph = dispatch_tool("graph_get", {"limit": 1})
    due = dispatch_tool("feed_due", {})
    print(result_as_text({"graph_get": graph, "feed_due": due}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GraphRecall MCP server (NAV-28)")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Call graph_get + feed_due and print JSON (no stdio MCP loop)",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print tool definitions as JSON and exit",
    )
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Force stub mode (print map; do not start MCP stdio)",
    )
    args = parser.parse_args(argv)

    if args.list_tools:
        slim = [
            {
                k: v
                for k, v in t.items()
                if k in ("name", "description", "inputSchema", "route")
            }
            for t in TOOL_DEFS
        ]
        print(json.dumps(slim, indent=2))
        return 0

    if args.self_check:
        return _self_check()

    if args.stub:
        _print_stub_banner()
        return 0

    if not _mcp_available():
        _print_stub_banner()
        print(
            "mcp package not installed — stub only. "
            "Use --self-check to probe the API.",
            file=sys.stderr,
        )
        return 0

    try:
        asyncio.run(_run_mcp_stdio())
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
