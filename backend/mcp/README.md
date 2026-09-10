# GraphRecall MCP server (NAV-28)

Thin **HTTP adapters** from MCP tools → existing FastAPI routes. No business-logic fork; no FastAPI app import (avoids circular imports).

## Auth

| Env | Default | Purpose |
|---|---|---|
| `GRAPHRECALL_API_BASE` | `http://127.0.0.1:8000` | Local/dev FastAPI base URL |
| `GRAPHRECALL_API_TOKEN` | _(required for authed routes)_ | Bearer **JWT** from existing GraphRecall auth |
| `GRAPHRECALL_MCP_TIMEOUT` | `60` | httpx timeout seconds |

- Agent callers use a user JWT (`Authorization: Bearer <token>`).
- **No API-key middleware yet** (Backend Engineer: may add later via `GRAPHRECALL_API_KEY`).
- **Never commit tokens.** Pass via shell env or Cursor MCP `env`.

## Run

From repo root (with `httpx` available; `mcp>=1.0.0` for real stdio):

```bash
export GRAPHRECALL_API_BASE=http://127.0.0.1:8000
export GRAPHRECALL_API_TOKEN='<jwt>'

# List tools / route map
python -m backend.mcp.server --list-tools
python -m backend.mcp.server --stub

# Probe API (graph_get + feed_due); JSON errors if API down
python -m backend.mcp.server --self-check

# Stdio MCP (requires: pip install 'mcp>=1.0.0')
python -m backend.mcp.server
```

`mcp` is listed in root `requirements.txt` (`mcp>=1.0.0`). If the SDK is missing, the entrypoint still runs in **stub mode** and documents tools.

### Cursor MCP config snippet

```json
{
  "mcpServers": {
    "graphrecall": {
      "command": "python",
      "args": ["-m", "backend.mcp.server"],
      "cwd": "/Users/naveenus/Projects/GraphRecall",
      "env": {
        "GRAPHRECALL_API_BASE": "http://127.0.0.1:8000",
        "GRAPHRECALL_API_TOKEN": "<paste JWT — do not commit>"
      }
    }
  }
}
```

## Tool → route map

| Tool | HTTP |
|---|---|
| `concepts_dump` | `POST /api/concepts/dump` |
| `ingest_notes` | `POST /api/v2/ingest` |
| `ingest_url` | `POST /api/v2/ingest/url` |
| `ingest_youtube` | `POST /api/v2/ingest/youtube` |
| `ingest_chat_transcript` | `POST /api/v2/ingest/chat-transcript` |
| `graph_get` | `GET /api/graph3d` |
| `nodes_search` | `GET /api/graph3d/search` |
| `nodes_create` | `POST /api/nodes` |
| `uploads_list` | `GET /api/uploads` |
| `feed_due` | `GET /api/feed/due-count` |
| `feed_get` | `GET /api/feed` |
| `stats_get` | `GET /api/feed/stats` |
| `chat_ask` | `POST /api/chat` (non-stream; SSE at `/api/chat/stream` not wrapped) |

Skeleton **done when** `concepts_dump` + `graph_get` (or `nodes_search`) can hit a live FastAPI with a valid JWT.

## Gaps vs Backend provisional design

- **No `notes.create` route** — `/api/notes` is GET/DELETE only; use `ingest_notes` → `POST /api/v2/ingest`.
- **`uploads` create** is multipart (`POST /api/uploads`); skeleton exposes `uploads_list` only (multipart create deferred).
- **`nodes_search`** uses `GET /api/graph3d/search` (no dedicated `/api/nodes` search).
- **API key middleware** not implemented; JWT only.
- Layout is flat (`tools.py`) rather than `tools/*.py` + `client.py` — same HTTP adapters, easier to split later.

## Layout

```
backend/mcp/
  __init__.py
  server.py      # stdio MCP + stub / --self-check
  tools.py       # schemas + httpx handlers
  README.md
```
