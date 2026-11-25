# Agent bridge: implementation status

Branch `feat/agent-bridge-mcp` (base `main`). Grep for `TODO(agent-bridge)` to find
every open item in code.

## Done (scaffold, tested)

- [x] **Migration** `backend/db/migrations/026_agent_bridge.sql`: `agent_api_keys`,
      `agent_feed_items`, `agent_daily_digests` and `agent_requests`. It is idempotent
      (re-run is tested) and uses the repo's raw-SQL migration style; `backend/db/migrate.py`
      applies it once. (Numbered 015 on the original bridge branch.)
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

## Hardening pass 1 (review of d36c66e by Coder Bot 2's E2E run)

- [x] **Questions reach terminal states.** A question past `expires_at` with no live lease
      becomes `expired`. One whose lease lapsed after `DEFAULT_MAX_ATTEMPTS` (3) claims becomes
      `failed` ("Agent did not answer after 3 attempts"). This happens lazily (a user-scoped
      sweep on get/list/claim) and through a global job, `python -m backend.agent_bridge.jobs`
      (`sweep_stale_requests`). `list_pending_questions` hides exhausted and expired questions.
      The SSE stream ends with `{"status": …, "terminal": true}` for answered, expired,
      failed and cancelled.
      **TODO(agent-bridge):** schedule the sweep job (a Render cron job every 5 min, or a
      lifespan loop). Until then the lazy sweep keeps each user's own view correct.
  Tests: `test_past_deadline_question_becomes_expired`, `test_exhausted_attempts_become_failed`,
  `test_last_attempt_in_progress_is_listed_but_not_claimable`,
  `test_deadline_does_not_cut_a_live_lease`, `test_sweep_job_is_global_and_counts`,
  `test_status_stream_surfaces_terminal_states`, `test_terminal_states_sweep_and_malformed_ids` (Postgres).
- [x] **http(s)-only URLs** for `source_url` and citation `url` (`dedupe.is_safe_http_url`).
      It rejects `javascript:`, `data:`, `file:`, missing hosts, and control characters,
      spaces or backslashes. Clients must render answer, card title and summary text as
      **plain text** (see PROPOSAL.md).
  Tests: `test_is_safe_http_url_rejects/accepts`, `test_citation_urls_must_be_http`,
  `test_feed_source_url_must_be_http`.
- [x] **Malformed ids → 400** in REST and `invalid_arguments` in MCP (was a 500 or
      `internal` error). Repositories return `None` for non-UUIDs.
  Tests: `test_malformed_ids_are_invalid_arguments_not_internal`, `test_rest_malformed_ids_return_400`,
  `test_repo_tolerates_malformed_ids`, `test_validation_errors_are_json_serializable` (the E2E
  rerun found that pydantic error context made MCP responses unserialisable).
- [x] **Feed injection respects `max_items` and `domains`.** Curated cards take at most
      half the page (and never more than 5). When a topic filter is active, cards are kept
      only if they are tagged with a concept in one of those domains.
  Tests: `test_merge_respects_max_items`, `test_domain_filter_on_agent_cards`.
- [x] **Only active keys count toward the 5-key limit** (expired and revoked keys don't).
  Test: `test_expired_and_revoked_keys_do_not_count_toward_limit`.
- [x] **Feed state machine.** pending → approved/rejected/expired, and approved → rejected.
      Rejected is final: approving it gives **409**. Same-state calls are idempotent.
  Tests: `test_feed_state_machine`, `test_feed_state_machine_batch_atomicity_cap_audit` (Postgres).
- [x] **`AGENT_KEY_PEPPER` fails closed** when `ENVIRONMENT=production`: key auth returns 401,
      key creation returns 503, and `backend.main` / the standalone app refuse to start. In dev
      it logs a warning once.
  Tests: `test_pepper_fails_closed_in_production`, `test_pepper_warns_in_dev`.
- [x] **Per-user enqueue rate limit** (`AGENT_BRIDGE_ENQUEUE_PER_HOUR`, default 20) → 429.
  Test: `test_enqueue_is_rate_limited_per_user`.
- [x] **The webhook is dispatched in the background** with bounded retry: 3 attempts,
      exponential backoff, retrying on 5xx, 429 and network errors and giving up on other 4xx.
  Tests: `test_enqueue_does_not_wait_for_webhook`, `test_webhook_bounded_retry`,
  `test_dispatch_in_background_returns_immediately`.

## Hardening pass 2 (Coder Bot 3's security review of d36c66e)

1. [x] **ISO-8601 timestamps** with `T` and an offset everywhere (`serialization.iso`/`to_jsonable`;
   naive values are treated as UTC). Test: `test_every_bridge_timestamp_is_iso8601_with_T_and_offset`.
2. [x] **Quotas, behind a pluggable limiter** (`limits.py`). There is a `RateLimiter`
   protocol with in-memory, Postgres (`agent_rate_limits` upsert, shared across workers)
   and Redis (optional) backends. Selection uses `AGENT_BRIDGE_RATE_LIMIT_BACKEND`;
   otherwise it is Redis if `REDIS_URL` is set, Postgres in production, and memory in dev.
   Limits:
   - MCP calls per key per minute: 120.
   - Enqueues per user per hour: 20.
   - Proposals per key per day: 100 (`AGENT_BRIDGE_PROPOSALS_PER_KEY_PER_DAY`).
   - Pending cards created per user per day: 50 (`AGENT_BRIDGE_MAX_PENDING_PER_DAY`), checked
     inside the insert transaction.
   Tests: `test_daily_pending_cap_per_user`, `test_cap_exceeded_mid_batch_writes_nothing`,
   `test_per_key_daily_proposal_limit`, `test_in_memory_limiter_window`,
   `test_postgres_limiter_uses_shared_counter`, `test_limiter_from_env`,
   `test_mcp_rate_limit_uses_services_limiter`, plus 8 concurrent hits on two
   `PostgresRateLimiter`s against real Postgres (exactly 5 of limit 5 admitted).
3. [x] **Audit log** (`027_agent_bridge_audit.sql` → `agent_audit_log`). It records:
   - every successful tool call (`tool_call`, or `answer_submitted` for submit_answer);
   - `key_created` and `key_revoked`;
   - `feed_item_approved` and `feed_item_rejected`;
   - `question_enqueued`.

   Details hold **metadata only** (counts and ids, never text). Users read it at
   `GET /api/agent-bridge/audit`. Audit failures never break a call.
   Test: `test_audit_log_records_metadata_only`, plus the Postgres round trip.
4. [x] **Malformed ids → 400** (above), and **`conversation_id` must belong to the user**
   (404 otherwise, 400 if malformed). Test: `test_conversation_id_must_belong_to_user` (cross-user).
5. [x] **The standalone app refuses to start** unless `AGENT_BRIDGE_ENABLED=1` (exit 2;
   `--list-tools` still works).
   - **Host/Origin allowlist:** localhost by default, plus `AGENT_BRIDGE_ALLOWED_HOSTS`,
     `RENDER_EXTERNAL_HOSTNAME` and `AGENT_BRIDGE_ALLOWED_ORIGINS`.
   - The app's own guard runs before auth: a foreign Host gets **421**, a foreign Origin
     gets **403**, and a missing Origin is allowed.
   - The same lists go to the SDK's `TransportSecuritySettings`.

   Tests: `test_standalone_refuses_without_flag`, `test_host_allowed_patterns`,
   `test_dns_rebinding_guard`.
6. [x] **Webhook event id and timestamp.**
   - Headers: `X-GraphRecall-Event-Id`, `X-GraphRecall-Timestamp`, and
     `X-GraphRecall-Signature: t=…,id=…,v1=HMAC(secret, "t.id.body")`.
   - The id stays the same across retries.
   - `verify_webhook()` plus `ReplayGuard` reject reused ids. Receivers must dedupe on the
     event id.

   Tests: `test_signature_binds_event_id`, `test_replay_guard_rejects_reused_ids`,
   `test_webhook_sends_id_and_timestamp_stable_across_retries`.
7. [x] **Atomic `propose_feed_items`.** The whole batch is validated first. It is then
   written in one transaction, under a per-user `pg_advisory_xact_lock`, so a failure or
   cap breach rolls everything back. Tests: `test_invalid_item_anywhere_in_batch_writes_nothing`,
   `test_batch_with_internal_duplicates_resolves_in_order`, and the Postgres rollback test (a CHECK
   violation mid-batch leaves 0 rows).
8. [x] **Agent text is untrusted.** `untrusted.wrap_untrusted()` / `agent_answer_for_prompt()`
   delimit it and neutralise forged markers. Chat does not consume agent answers yet; a
   SECURITY TODO in `routers/chat.py` says to wrap them when it does. The prompt-injection
   risk is noted in PROPOSAL.md. Test: `test_wrap_untrusted_delimits_and_neutralises_markers`.

## Not in this branch (owned elsewhere)

- **iOS** (Coder Bot 3, `feat/agent-bridge-ios`): unknown feed types currently fall back
  to flashcards in `FeedModels.swift` line 29. `agent_curated` cards need their own case
  before the flag is turned on for iOS users. Not touched here.

## Tests

```bash
pytest backend/tests/test_agent_bridge.py backend/tests/test_agent_bridge_hardening.py \
       backend/tests/test_agent_bridge_security.py              # no DB needed
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
2. **Deploy config:** set `AGENT_BRIDGE_ENABLED`, `AGENT_KEY_PEPPER` (required in
   production now), `AGENT_BRIDGE_ALLOWED_HOSTS` if the host is not `RENDER_EXTERNAL_HOSTNAME`,
   and the webhook env. Schedule `python -m backend.agent_bridge.jobs`.
3. **Chat handoff:** offer "ask my agent" as a tool in the chat graph, or a client button
   (see the TODO in `routers/chat.py`). Then show answers inside the conversation, and
   optionally save them to `chat_messages`.
4. **Retention:** prune `agent_rate_limits` windows and old `agent_audit_log` rows.
5. **Expiry jobs:** schedule the request sweep (done in code), and add expiry of stale
   pending feed items (the `expired` transition exists; nothing sets it yet).
6. **Better reads:** semantic `search_concepts` via `retrieval_service`, exam/goal
   context in the profile, and the user's timezone for "today".
7. **Feedback loop:** expose approve/reject outcomes to the agent (for example a
   `get_feed_feedback` tool), and support like/save on `agent:` feed ids (today the feed
   like/save routes expect flashcard/quiz ids).
8. **Webhooks:** per-user webhook URL and secret, plus a durable outbox (retries today are
   in-process only). Grok Bot needs a
   reachable inbound URL; until then it polls on a routine.
9. **Digest UI:** show `agent_daily_digests` as a header card.
10. **Audit UI:** show `GET /api/agent-bridge/audit` under Settings → Connected agents.

## Test results (local box, Python 3.12)

At the original commit d36c66e:

- `backend/tests/test_agent_bridge.py`: **27 passed** on `mcp` 2.3.0, and 27 passed on 1.30.0.
- `backend/tests/test_agent_bridge_postgres.py`: **2 passed** against a throwaway local
  Postgres 16 (`pgserver`). Without `AGENT_BRIDGE_TEST_DATABASE_URL` they skip.
- Full suite (`pytest backend/tests tests`): **73 passed, 5 failed**. The 5 failures are
  pre-existing and fail identically on `main` (44 passed, 5 failed):
  `test_extraction.py` × 4 and `test_modern_graphs.py::test_chat_graph_flow`. They are
  unrelated to this branch.

After the hardening passes (this commit):

- Agent-bridge tests (no DB): `test_agent_bridge.py` 27, `test_agent_bridge_hardening.py` 51,
  and `test_agent_bridge_security.py` 23. That is **101 passed** on `mcp` 2.3.0 and the same
  101 on 1.30.0.
- `test_agent_bridge_postgres.py`: **4 passed** against throwaway `pgserver` Postgres 16
  (with migrations 015 and 016, each run twice).
- Full suite: **149 passed, 5 failed**. These are the same 5 pre-existing failures as on `main`.
- Coder Bot 2's E2E scripts were rerun against a scratch local stack:
  - **Stack:** uvicorn on 127.0.0.1:8077 with `DEBUG=true` (test-token auth), a scratch
    Postgres 16 and Neo4j 5.26 Community.
  - **e2e.py: 50/50 PASS.** Exhausted questions now show `failed`, TTL-expired ones
    `expired`, and non-UUID ids give `invalid_arguments`.
  - **extra2.py:**
    - Concurrent claims: 1 winner of 20; anonymous claims spread 5/5 unique.
    - `javascript:` citation: rejected.
    - Foreign Host: 421.
    - Rate limit: 429 with `Retry-After`; unauthenticated calls get 401.
    - Key limit: a 6th key is allowed once the other 5 are expired.
    - Reject then approve: 409.
    - `max_items=1`: 1 item.
  - **Webhooks:** all 10 verified, ids unique, replays rejected, and wrong-secret or
    tampered bodies rejected.
