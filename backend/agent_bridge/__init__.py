"""Agent bridge: lets an external always-on agent (e.g. Grok Bot) work with GraphRecall.

Two directions (see docs/agent-bridge/PROPOSAL.md):

1. Agent -> GraphRecall over MCP (streamable HTTP): read the user's knowledge profile,
   propose curated feed items, and answer queued questions.
2. GraphRecall -> Agent through an async queue (``agent_requests``): the in-app
   assistant enqueues a question; the agent polls/claims it over MCP and submits an answer.

Everything is gated behind ``AGENT_BRIDGE_ENABLED=1`` so merging this does not change
production behaviour until it is switched on.
"""

import os

__all__ = ["bridge_enabled"]


def bridge_enabled() -> bool:
    return os.environ.get("AGENT_BRIDGE_ENABLED", "").strip().lower() in {"1", "true", "yes"}
