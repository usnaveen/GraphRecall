# Connecting Grok Bot to GraphRecall

## 1. Turn the bridge on (backend)

Set these on the backend service (Render dashboard / `.env`). Nothing in `render.yaml`
was changed by this branch.

| Env | Required | Purpose |
|---|---|---|
| `AGENT_BRIDGE_ENABLED=1` | yes | Mounts `/mcp/agent/` and `/api/agent-bridge/*`; adds agent cards to `/api/feed` |
| `AGENT_KEY_PEPPER` | **yes in production** | Secret mixed into key hashes. With `ENVIRONMENT=production` and no pepper, the app refuses to start and key auth fails closed; in dev it only warns. Changing it invalidates all keys |
| `AGENT_BRIDGE_ALLOWED_HOSTS` | if not on Render | Comma-separated Host allowlist (`host` or `host:*`). Localhost and `RENDER_EXTERNAL_HOSTNAME` are always allowed; other hosts get 421 |
| `AGENT_BRIDGE_ALLOWED_ORIGINS` | optional | Browser Origins allowed (a missing Origin is fine for server-to-server MCP); others get 403 |
| `AGENT_BRIDGE_RATE_LIMIT_BACKEND` | optional | `memory`, `postgres` or `redis` (default: redis if `REDIS_URL` is set, postgres in production, else memory) |
| `AGENT_BRIDGE_MCP_CALLS_PER_MIN` / `_ENQUEUE_PER_HOUR` / `_PROPOSALS_PER_KEY_PER_DAY` / `_MAX_PENDING_PER_DAY` | optional | Limits (defaults 120 / 20 / 100 / 50) |
| `AGENT_BRIDGE_WEBHOOK_URL` | optional | Where to POST `agent_request.created` events (in the background, up to 3 attempts) |
| `AGENT_BRIDGE_WEBHOOK_SECRET` | with URL | HMAC secret. Headers: `X-GraphRecall-Event-Id`, `X-GraphRecall-Timestamp`, `X-GraphRecall-Signature: t=…,id=…,v1=…`. Receivers must dedupe on the event id (`verify_webhook` + `ReplayGuard`) |

Migrations `015_agent_bridge.sql` and `016_agent_bridge_audit.sql` (in
`backend/db/migrations/`) run automatically on boot, like every file in that folder.
Schedule `python -m backend.agent_bridge.jobs` (for example every 5 minutes) to expire
stale questions; TODO(agent-bridge).

Standalone alternative (local dev): `AGENT_BRIDGE_ENABLED=1 python -m backend.agent_bridge.mcp_app --port 8100`
serves the same MCP app at `http://127.0.0.1:8100/`. It refuses to start without the flag.

## 2. Create an agent key (app)

`POST /api/agent-bridge/keys` with the user's normal Google bearer token:

```json
{"name": "Grok Bot", "scopes": ["read:knowledge", "write:feed", "bridge:answer"], "expires_in_days": 90}
```

The response contains `api_key` (`grk_…`) **once**. TODO(agent-bridge): a Settings →
"Connected agents" screen in iOS/web to create, copy and revoke keys.

## 3. Register the MCP server as a connector in Grok Bot

Add a **custom MCP connector** (remote / streamable HTTP):

- **URL:** `https://<your-graphrecall-backend>/mcp/agent/` (keep the trailing slash; without
  it Starlette answers with a 307 redirect)
- **Header:** `Authorization: Bearer grk_…`
- **Transport:** streamable HTTP (JSON responses, stateless)

Ask Grok Bot to "add a custom MCP connector" and give it the URL and header. The key
goes in through the connector's secret/header field, never in chat or a routine prompt.
Check the setup by asking it to call `get_knowledge_profile`.

Quick manual check:

```bash
curl -s https://<backend>/mcp/agent/ \
  -H "Authorization: Bearer $GRK_KEY" \
  -H "Accept: application/json, text/event-stream" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## 4. Routines

### Nightly curation (e.g. 01:00 Asia/Calcutta, daily)

> You curate tomorrow's GraphRecall feed for me.
> 1. Call `get_knowledge_profile` and `list_due_reviews` on the GraphRecall connector.
>    Note my weakest concepts and anything due.
> 2. Check my calendar for exams, interviews or deadlines in the next 14 days, and treat
>    their topics as top priority.
> 3. Look at new posts from my Substack subscriptions and newsletter emails from the
>    last 24 hours. Pick only items that teach or reinforce a concept I'm weak in, or an
>    upcoming exam topic. Skip promotions and anything personal.
> 4. Choose 3–8 items. For each, call `propose_feed_items` with: a short `title`; a
>    `summary` of at most 5 sentences in your own words (never paste email text); a
>    one-sentence `reason` tied to my weak concept or exam; the canonical `source_url`;
>    `source_kind` (`substack`/`email`/`web`/`exam`); `concept_ids` from
>    `search_concepts` when there is a clear match; `target_date` = tomorrow; and
>    `idempotency_key` = `nightly-<YYYY-MM-DD>-<n>`. For exam topics, add one
>    `item_kind: "flashcard"` card with `flashcard.front` and `flashcard.back`.
> 5. Call `schedule_daily_digest` for tomorrow with a one-line title and the item ids.
> 6. Don't message me unless something failed.

### Answer handed-off questions (every 15 minutes, or on webhook)

> Check GraphRecall for questions my in-app assistant handed to you.
> 1. Call `list_pending_questions`. If none are `claimable`, stop silently.
> 2. For each claimable one, run `claim_question` with its `request_id` and keep the
>    `claim_token`.
> 3. Use `get_knowledge_profile`, `search_concepts` and `get_concept_neighborhood` to
>    pitch the answer at my level, plus web research if needed.
> 4. Call `submit_answer` with `answer_markdown` (≤ 400 words, direct, cite sources) and
>    `citations`. If you can't answer, set `error` with a short reason instead.
