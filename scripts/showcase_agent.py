"""Give the showcase learner (scripts/showcase_account.py) a connected agent with two suggestions
waiting in the Agent Inbox, the way a real agent would: a scoped key from the API, then
`propose_feed_items` over the MCP endpoint. Local DEBUG API only (Bearer showcase-token).

The key's secret is used in memory for this run and never printed or stored.

    PYTHONPATH=. .venv/bin/python scripts/showcase_agent.py [--api http://localhost:8001]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import urllib.request
from datetime import date
from urllib.parse import urlparse

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

SUGGESTIONS = [
    {
        "title": "Feature store or model registry: which problem each one solves",
        "summary": "A feature store keeps the inputs a model sees identical in training and in serving, "
                   "and lets teams reuse them. A model registry versions the trained models themselves, "
                   "with their metrics and stage (staging, production). One guards the data going in; "
                   "the other guards what gets deployed.",
        "reason": "Both are on your resume, and both are still shaky on your knowledge map.",
        "source_kind": "other",
        "item_kind": "article",
        "idempotency_key": "showcase-feature-store-vs-registry",
    },
    {
        "title": "Training-serving skew in one question",
        "summary": "A quick check before your MLOps interview.",
        "reason": "You scored lowest on this one last week.",
        "source_kind": "exam",
        "item_kind": "flashcard",
        "flashcard": {
            "front": "Your model scores 0.92 offline but much worse in production, with the same code. "
                     "What is the most likely cause, and how does a feature store help?",
            "back": "Training-serving skew: features computed differently (or from different data) in "
                    "training and in serving. A feature store computes each feature once and serves the "
                    "same values to both.",
        },
        "idempotency_key": "showcase-training-serving-skew",
    },
]


def _post(api: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(f"{api}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer showcase-token",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


async def propose(api: str, secret: str) -> dict:
    items = [{**s, "target_date": date.today().isoformat()} for s in SUGGESTIONS]
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {secret}"}, timeout=60) as http:
        async with streamable_http_client(f"{api}/mcp/agent/", http_client=http) as (r, w), \
                ClientSession(r, w) as session:
            await session.initialize()
            result = await session.call_tool("propose_feed_items", {"items": items})
            return json.loads(result.content[0].text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8001")
    args = ap.parse_args()
    if (urlparse(args.api).hostname or "") not in {"localhost", "127.0.0.1"}:
        raise SystemExit("refusing: local API only")
    created = _post(args.api, "/api/agent-bridge/keys",
                    {"name": "Claude Code", "scopes": ["read:knowledge", "write:feed"], "expires_in_days": 30})
    print("key", created["key"]["key_prefix"], created["key"]["scopes"])
    out = asyncio.run(propose(args.api, created["api_key"]))
    data = out.get("data", out)
    for item in data.get("items", []):
        print(" ", "created" if item.get("created") else "existing", item.get("id"))


if __name__ == "__main__":
    main()
