# Agent bridge: implementation status

Branch `feat/agent-bridge-mcp` (base `main`). Grep for `TODO(agent-bridge)` to find
every open item in code.

## Done (scaffold, tested)

- [x] **Migration** `backend/db/migrations/015_agent_bridge.sql`: `agent_api_keys`,
      `agent_feed_items`, `agent_daily_digests` and `agent_requests`. It is idempotent
      (re-run is tested) and uses the repo's raw-SQL migration style, so it runs on boot.
- [x] **Scoped agent keys** (`backend/agent_bridge/keys.py`, `auth.py`): `grk_<prefix>_<secret>`
      format, peppered SHA-256 hash only, scopes `read:knowledge` / `write:feed` /
      `bridge:answer`, expiry, revocation, and a constant-time compare.
- [x] **Repository** (`repository.py`): Postgres implementation plus an in-memory twin
      with the same semantics.
- [x] **Knowledge reads** (`knowledge.py`): profile, search, bounded 1-hop
      neighbourhood, due reviews and recent activity, using the existing Neo4j `Concept`
      nodes, `proficiency_scores` and `SpacedRepetitionService`.
- [x] **MCP tools** (`tools.py`): all 10 tools, with pydantic-validated args
      (`extra="forbid"`), per-tool scope checks and uniform `{ok, data | error}` results.
- [x] **MCP server** (`mcp_app.py`): official SDK low-level server over **streamable
      HTTP** (stateless, JSON responses), with a bearer-key auth wrapper and a per-key
      rate limit. It mounts at `/mcp/agent/` in `backend/main.py` or runs standalone, and
      supports `mcp` 1.x and 2.x (tests pass on 1.30.0 and 2.3.0).
- [x] **App REST** (`router.py`): keys, feed-item approval, and the ask-my-agent queue
      (enqueue, list, get, SSE stream, cancel).
- [x] **Feed integration** (`feed_integration.py`, `routers/feed.py`): approved items
      become `FeedItemType.AGENT_CURATED` feed items with provenance, behind the flag.
- [x] **Webhook stub** (`webhook.py`): HMAC-signed `agent_request.created` events, plus a
      verifier.
- [x] **NAV-28 stdio server** (`backend/mcp/server.py`) fixed for `mcp` 2.x. It crashed
      with `AttributeError: 'Server' object has no attribute 'list_tools'`.
- [x] Docs: `PROPOSAL.md`, `GROK_BOT_SETUP.md` (connector and routine prompts) and this file.

## Security requirements (review checklist)

- [x] **Ownership on every tool and endpoint.** Keys are bound to one `user_id`. Tools
      take no `user_id` argument (rejected as an unknown arg). Every SQL and Cypher query
      filters by the owner; Neo4j neighbourhoods require both endpoints to be owned.
      Foreign ids look exactly like missing ones.
  Tests: `test_reads_are_scoped_to_key_owner` (also asserts every recorded query was
  user-filtered), `test_writes_cannot_touch_other_users_data`,
  `test_questions_are_scoped_to_key_owner`, `test_tools_reject_user_id_argument`,
  `test_mcp_http_auth_and_tool_call` (two keys on the same server get no principal
  bleed), `test_rest_keys_approvals_and_ask_agent` (user B gets 404 on A's key, item and
  request), and `test_keys_feed_dedupe_and_ownership` (real Postgres).
- [x] **Idempotent `propose_feed_items`.** It accepts a client `idempotency_key`, with a
      partial unique index on `(user_id, idempotency_key)`. It also dedupes on
      `UNIQUE (user_id, dedupe_key, target_date)`, where `dedupe_key` is the SHA-256 of
      the normalised URL (scheme, `www.`, tracking params, fragment and trailing slash are
      ignored) or of the normalised title + summary. `INSERT … ON CONFLICT DO NOTHING`
      returns the existing row, with `created: false, deduplicated: true`.
  Tests: `test_propose_is_idempotent` and `test_keys_feed_dedupe_and_ownership` (real
  Postgres constraint).
- [x] **Atomic `claim_question` with a lease.** A single `UPDATE … WHERE id = (SELECT …
      FOR UPDATE SKIP LOCKED LIMIT 1)` sets a fresh `claim_token`, `lease_expires_at`
      and `attempts + 1`. `submit_answer` needs a matching token **and** an unexpired
      lease. Expired leases can be reclaimed (the old token stops working), with a
      maximum of 3 attempts.
  Tests: `test_concurrent_claim_is_atomic_and_lease_expires` (20 concurrent claims
  against real Postgres, exactly one winner),
  `test_concurrent_claims_have_exactly_one_winner`,
  `test_lease_expiry_allows_reclaim_and_invalidates_old_token` and
  `test_max_attempts_and_cancel`.
- [x] Scope enforcement on every tool (`test_every_tool_requires_its_scope`), plus
      revoked, expired and tampered key rejection.

## Tests

```bash
pytest backend/tests/test_agent_bridge.py                       # no DB needed
AGENT_BRIDGE_TEST_DATABASE_URL=postgresql://…/throwaway \
  pytest backend/tests/test_agent_bridge_postgres.py            # real Postgres, own schema
```

The Postgres tests skip unless that env var is set. Locally they were run against a
throwaway `pgserver` instance, never a real GraphRecall database.

## TODO for the next coding agent (priority order)

1. **UI (iOS + web):** render `agent_curated` feed items with the "Curated by your agent"
   label, source link and reason. Build a pending-approval inbox
   (`GET /api/agent-bridge/feed-items` plus approve/reject), Settings → Connected agents
   (create/copy/revoke keys, last used), and an "Ask my agent" action in chat with a
   pending bubble driven by `/requests/{id}/stream`.
2. **Deploy config:** set `AGENT_BRIDGE_ENABLED`, `AGENT_KEY_PEPPER` (and fail closed if
   it is missing in production) and the webhook env on the backend. Then add
   `TransportSecuritySettings` (allowed hosts) for the public hostname.
3. **Chat handoff:** offer "ask my agent" as a tool in the chat graph, or a client button
   (see the TODO in `routers/chat.py`). Then show answers inside the conversation, and
   optionally save them to `chat_messages`.
4. **Rate limits/quotas:** a shared limiter (Postgres or Redis) for multi-worker
   deployments, a per-user enqueue quota, and limits on proposals per day.
5. **Expiry jobs:** mark `agent_requests` past `expires_at` as `expired`, and stale
   pending feed items as `expired`.
6. **Better reads:** semantic `search_concepts` via `retrieval_service`, exam/goal
   context in the profile, and the user's timezone for "today".
7. **Feedback loop:** expose approve/reject outcomes to the agent (for example a
   `get_feed_feedback` tool), and support like/save on `agent:` feed ids (today the feed
   like/save routes expect flashcard/quiz ids).
8. **Webhooks:** per-user webhook URL and secret, plus retries/outbox. Grok Bot needs a
   reachable inbound URL; until then it polls on a routine.
9. **Digest UI:** show `agent_daily_digests` as a header card.
10. **Audit log:** record each MCP call (key id, tool, timestamp) so users can see what
    their agent read.

## Test results when this branch was opened (local box, Python 3.12)

- `backend/tests/test_agent_bridge.py`: **27 passed** on `mcp` 2.3.0, and 27 passed on 1.30.0.
- `backend/tests/test_agent_bridge_postgres.py`: **2 passed** against a throwaway local
  Postgres 16 (`pgserver`). Without `AGENT_BRIDGE_TEST_DATABASE_URL` they skip.
- Full suite (`pytest backend/tests tests`): **73 passed, 5 failed**. The 5 failures are
  pre-existing and fail identically on `main` (44 passed, 5 failed):
  `test_extraction.py` × 4 and `test_modern_graphs.py::test_chat_graph_flow`. They are
  unrelated to this branch.
