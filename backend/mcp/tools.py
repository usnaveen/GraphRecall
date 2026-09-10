"""MCP tool definitions and HTTP handlers for GraphRecall FastAPI.

Auth: GRAPHRECALL_API_BASE (default http://127.0.0.1:8000),
      GRAPHRECALL_API_TOKEN (Bearer JWT from existing auth).
No secrets in repo — pass token via env / Cursor MCP config.

Uses httpx when installed; otherwise stdlib urllib (skeleton stays runnable).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

try:
    import httpx as _httpx
except ImportError:  # pragma: no cover
    _httpx = None  # type: ignore

DEFAULT_BASE = "http://127.0.0.1:8000"
TIMEOUT_S = float(os.environ.get("GRAPHRECALL_MCP_TIMEOUT", "60"))


def api_base() -> str:
    return os.environ.get("GRAPHRECALL_API_BASE", DEFAULT_BASE).rstrip("/")


def api_token() -> Optional[str]:
    return os.environ.get("GRAPHRECALL_API_TOKEN") or None


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    token = api_token()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _request_urllib(
    method: str,
    url: str,
    *,
    json_body: Any = None,
    params: Optional[dict[str, Any]] = None,
) -> tuple[int, Any]:
    if params:
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{q}"
    data = None
    headers = _headers()
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
            try:
                return status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return status, {"raw": raw[:2000]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            body: Any = json.loads(raw) if raw else {"detail": e.reason}
        except json.JSONDecodeError:
            body = {"raw": raw[:2000], "detail": str(e.reason)}
        return e.code, body


def api_request(
    method: str,
    path: str,
    *,
    json_body: Any = None,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Call local FastAPI; always return a JSON-serializable dict (never raise)."""
    url = f"{api_base()}{path}"
    try:
        if _httpx is not None:
            with _httpx.Client(timeout=TIMEOUT_S) as client:
                resp = client.request(
                    method.upper(),
                    url,
                    headers=_headers(),
                    json=json_body,
                    params=params,
                )
            try:
                body: Any = resp.json()
            except Exception:
                body = {"raw": resp.text[:2000]}
            status = resp.status_code
            ok = resp.is_success
        else:
            status, body = _request_urllib(
                method, url, json_body=json_body, params=params
            )
            ok = 200 <= status < 300

        if ok:
            return {"ok": True, "status": status, "data": body}
        return {
            "ok": False,
            "status": status,
            "error": body if isinstance(body, dict) else {"detail": body},
            "path": path,
        }
    except Exception as e:
        # Cover ConnectError / Timeout / URLError / etc.
        name = type(e).__name__
        msg = str(e)
        err_type = "connection_error"
        if "timeout" in name.lower() or "timed out" in msg.lower():
            err_type = "timeout"
        return {
            "ok": False,
            "status": 0,
            "error": {
                "type": err_type,
                "exception": name,
                "message": msg or f"API unreachable at {api_base()}",
                "hint": "Start FastAPI (uvicorn) and set GRAPHRECALL_API_BASE / TOKEN",
                "transport": "httpx" if _httpx is not None else "urllib",
            },
            "path": path,
        }


# ---------------------------------------------------------------------------
# Tool schemas (JSON Schema for MCP list_tools)
# ---------------------------------------------------------------------------

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "concepts_dump",
        "description": (
            "Dump concept names into GraphRecall (research + teach cards). "
            "Maps to POST /api/concepts/dump"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "concepts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concept names (max 40)",
                },
            },
            "required": ["concepts"],
        },
        "route": "POST /api/concepts/dump",
    },
    {
        "name": "ingest_notes",
        "description": (
            "Ingest free-text notes via LangGraph pipeline. "
            "Maps to POST /api/v2/ingest (no dedicated notes.create route)"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "title": {"type": "string"},
                "skip_review": {"type": "boolean", "default": True},
                "resource_type": {"type": "string"},
            },
            "required": ["content"],
        },
        "route": "POST /api/v2/ingest",
    },
    {
        "name": "ingest_url",
        "description": "Ingest an article URL. Maps to POST /api/v2/ingest/url",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        "route": "POST /api/v2/ingest/url",
    },
    {
        "name": "ingest_youtube",
        "description": (
            "Store a YouTube link as a note resource (no heavy processing). "
            "Maps to POST /api/v2/ingest/youtube"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["url"],
        },
        "route": "POST /api/v2/ingest/youtube",
    },
    {
        "name": "ingest_chat_transcript",
        "description": (
            "Ingest an LLM chat transcript. "
            "Maps to POST /api/v2/ingest/chat-transcript"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["content"],
        },
        "route": "POST /api/v2/ingest/chat-transcript",
    },
    {
        "name": "graph_get",
        "description": (
            "Fetch 3D knowledge-graph nodes/edges for the authed user. "
            "Maps to GET /api/graph3d"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "center_concept_id": {"type": "string"},
                "max_depth": {"type": "integer", "minimum": 1, "maximum": 5},
                "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
                "offset": {"type": "integer", "minimum": 0},
            },
        },
        "route": "GET /api/graph3d",
    },
    {
        "name": "nodes_search",
        "description": (
            "Search concepts for graph navigation. "
            "Maps to GET /api/graph3d/search (no /api/nodes search route)"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "maximum": 20},
            },
            "required": ["query"],
        },
        "route": "GET /api/graph3d/search",
    },
    {
        "name": "nodes_create",
        "description": "Create a manual concept node. Maps to POST /api/nodes",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "domain": {"type": "string"},
                "parent_concept_id": {"type": "string"},
                "position": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                    },
                },
            },
            "required": ["name"],
        },
        "route": "POST /api/nodes",
    },
    {
        "name": "uploads_list",
        "description": "List user uploads. Maps to GET /api/uploads",
        "inputSchema": {"type": "object", "properties": {}},
        "route": "GET /api/uploads",
    },
    {
        "name": "feed_due",
        "description": (
            "Due/overdue recall counts. Maps to GET /api/feed/due-count"
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "route": "GET /api/feed/due-count",
    },
    {
        "name": "feed_get",
        "description": "Active recall feed items. Maps to GET /api/feed",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_items": {"type": "integer", "maximum": 50},
                "item_types": {
                    "type": "string",
                    "description": "Comma-separated: flashcard,mcq,fill_blank,showcase",
                },
                "domains": {"type": "string"},
            },
        },
        "route": "GET /api/feed",
    },
    {
        "name": "stats_get",
        "description": "User learning stats. Maps to GET /api/feed/stats",
        "inputSchema": {"type": "object", "properties": {}},
        "route": "GET /api/feed/stats",
    },
    {
        "name": "chat_ask",
        "description": (
            "Non-streaming GraphRAG chat. Maps to POST /api/chat. "
            "For SSE use POST /api/chat/stream (not wrapped here)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "conversation_id": {"type": "string"},
                "user_id": {
                    "type": "string",
                    "description": (
                        "Required by ChatRequest schema; API uses JWT user. "
                        "Pass any non-empty string (e.g. 'mcp') if unknown."
                    ),
                },
            },
            "required": ["message"],
        },
        "route": "POST /api/chat",
    },
]


def tool_route_map() -> dict[str, str]:
    return {t["name"]: t["route"] for t in TOOL_DEFS}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

Handler = Callable[[dict[str, Any]], dict[str, Any]]


def handle_concepts_dump(args: dict[str, Any]) -> dict[str, Any]:
    return api_request(
        "POST",
        "/api/concepts/dump",
        json_body={"concepts": args.get("concepts") or []},
    )


def handle_ingest_notes(args: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "content": args["content"],
        "skip_review": args.get("skip_review", True),
    }
    if args.get("title") is not None:
        body["title"] = args["title"]
    if args.get("resource_type") is not None:
        body["resource_type"] = args["resource_type"]
    return api_request("POST", "/api/v2/ingest", json_body=body)


def handle_ingest_url(args: dict[str, Any]) -> dict[str, Any]:
    return api_request("POST", "/api/v2/ingest/url", json_body={"url": args["url"]})


def handle_ingest_youtube(args: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {"url": args["url"]}
    if args.get("title") is not None:
        body["title"] = args["title"]
    return api_request("POST", "/api/v2/ingest/youtube", json_body=body)


def handle_ingest_chat_transcript(args: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {"content": args["content"]}
    if args.get("title") is not None:
        body["title"] = args["title"]
    return api_request("POST", "/api/v2/ingest/chat-transcript", json_body=body)


def handle_graph_get(args: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key in ("center_concept_id", "max_depth", "limit", "offset"):
        if args.get(key) is not None:
            params[key] = args[key]
    return api_request("GET", "/api/graph3d", params=params or None)


def handle_nodes_search(args: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"query": args["query"]}
    if args.get("limit") is not None:
        params["limit"] = args["limit"]
    return api_request("GET", "/api/graph3d/search", params=params)


def handle_nodes_create(args: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in args.items() if v is not None}
    return api_request("POST", "/api/nodes", json_body=body)


def handle_uploads_list(args: dict[str, Any]) -> dict[str, Any]:
    return api_request("GET", "/api/uploads")


def handle_feed_due(args: dict[str, Any]) -> dict[str, Any]:
    return api_request("GET", "/api/feed/due-count")


def handle_feed_get(args: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key in ("max_items", "item_types", "domains"):
        if args.get(key) is not None:
            params[key] = args[key]
    return api_request("GET", "/api/feed", params=params or None)


def handle_stats_get(args: dict[str, Any]) -> dict[str, Any]:
    return api_request("GET", "/api/feed/stats")


def handle_chat_ask(args: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "message": args["message"],
        "user_id": args.get("user_id") or "mcp-agent",
    }
    if args.get("conversation_id") is not None:
        body["conversation_id"] = args["conversation_id"]
    return api_request("POST", "/api/chat", json_body=body)


HANDLERS: dict[str, Handler] = {
    "concepts_dump": handle_concepts_dump,
    "ingest_notes": handle_ingest_notes,
    "ingest_url": handle_ingest_url,
    "ingest_youtube": handle_ingest_youtube,
    "ingest_chat_transcript": handle_ingest_chat_transcript,
    "graph_get": handle_graph_get,
    "nodes_search": handle_nodes_search,
    "nodes_create": handle_nodes_create,
    "uploads_list": handle_uploads_list,
    "feed_due": handle_feed_due,
    "feed_get": handle_feed_get,
    "stats_get": handle_stats_get,
    "chat_ask": handle_chat_ask,
}


def dispatch_tool(name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    args = arguments or {}
    handler = HANDLERS.get(name)
    if handler is None:
        return {
            "ok": False,
            "status": 404,
            "error": {
                "type": "unknown_tool",
                "message": f"Unknown tool: {name}",
                "known": sorted(HANDLERS),
            },
        }
    try:
        return handler(args)
    except KeyError as e:
        return {
            "ok": False,
            "status": 400,
            "error": {
                "type": "missing_argument",
                "message": f"Missing required argument: {e}",
            },
        }
    except Exception as e:
        return {
            "ok": False,
            "status": 500,
            "error": {"type": type(e).__name__, "message": str(e)},
        }


def result_as_text(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, default=str)
