# GraphRecall v2 Deployment Plan (`DEPLOY-PLAN.md`)

> **Status:** Architecture & cost plan only (zero external cloud resources have been provisioned). Live provisioning awaits explicit user confirmation of vendor/budget.

## 1. Runtime Topology

GraphRecall v2 runs **4 stateless/stateful components** defined in `docker-compose.yml`:

| Service | Role | Key Runtime Requirement |
|---|---|---|
| `api` | FastAPI + LangGraph SSE + `/api/v2/agent` | Stateless HTTP/SSE container (`ENVIRONMENT=production`, `DATABASE_URL`, `NEO4J_URI`, `GOOGLE_API_KEY`) |
| `agent-worker` | Always-on daemon (`python -m backend.agent_v2.worker`) | Durable `FOR UPDATE SKIP LOCKED` polling loop with 300s crash-recovery lease, provenance gate, and `AGENT_V2_MAX_RPM` throttling |
| Postgres 17 + `pgvector` | Notes, chunks (`vector(768)`), LangGraph checkpointer, `agent_jobs`, `agent_insights`, `agent_runs` | Apply schema `backend/db/init.sql` + `backend/db/migrations/015_always_on_agent.sql` |
| Neo4j 5 | Concept knowledge graph (`Concept`, `RELATED_TO`, communities) | APOC enabled; indexed constraints per `backend/db/neo4j_client.py` |

---

## 2. Hosting Options & Estimated Monthly Costs

### Option A: Low-Cost Hobby / Portfolio Demo (`~$0–$15/month`)
- **App Compute (`api` + `agent-worker`):** Railway Hobby (`$5/mo` usage credit) or Render/Fly.io shared-cpu-1x (`~$5–$10/mo` for 2 small containers). *Note:* Free-tier sleep breaks background `agent-worker` continuity; keep at least `agent-worker` or HTTP cron wakeup active.
- **Postgres + `pgvector`:** Neon Free Tier (`$0/mo`, 0.5 GB storage, native `pgvector`) or Supabase Free Tier (`$0/mo`, pauses after 7d inactivity).
- **Neo4j:** Neo4j AuraDB Free (`$0/mo`, up to 200k nodes / 400k relationships).
- **LLM API:** Gemini Developer API pay-as-you-go (set `AGENT_V2_MAX_RPM=12` to stay inside free-tier limits or use billed tier for background synthesis).

### Option B: Always-On Small Team Production (`~$40–$110/month`)
- **App Compute:** Fly.io or Railway (`api` 1 GB RAM + `agent-worker` 512 MB RAM, always-on multi-machine option): `~$15–$25/mo`.
- **Postgres + `pgvector`:** Neon Launch (`$19/mo`+) or Supabase Pro (`$25/mo`, no inactivity pause, automated backups).
- **Neo4j:** AuraDB Professional (`~$65/mo` minimum for dedicated always-on SLA).

### Option C: Self-Hosted Single VPS (`~$12–$24/month`, Full Control)
- **Single VPS:** Hetzner CPX31 (4 vCPU, 8 GB RAM) or DigitalOcean Droplet running `docker compose up -d --build` (runs Postgres + `pgvector`, Neo4j 5, `api`, and `agent-worker` side-by-side behind Caddy/Cloudflare Tunnel HTTPS).
- Best performance-per-dollar for live portfolio demos because `api` and `agent-worker` talk to Postgres/Neo4j over local Docker bridge (`<1 ms` latency) with zero AuraDB pause risk.

---

## 3. Environment & Migration Checklist

Required environment variables (keep secrets out of git; use platform secret stores):
- `ENVIRONMENT=production` (switches LangGraph checkpointer from memory to PostgresSaver)
- `DATABASE_URL=postgresql://...`
- `NEO4J_URI=neo4j+s://...` (or `bolt://neo4j:7687` inside Compose)
- `NEO4J_USER`, `NEO4J_PASSWORD`
- `GOOGLE_API_KEY` (ensure billing/tier matches expected `AGENT_V2_MAX_RPM`)
- `AGENT_V2_MAX_RPM=12` (async token-interval throttle inside `GeminiLLMGateway`)

Schema setup before first worker boot:
1. Run `backend/db/init.sql` (or existing migrations `001`–`014`).
2. Apply `backend/db/migrations/015_always_on_agent.sql` (creates `agent_jobs`, `agent_insights`, `agent_runs`).

---

## 4. Verification & Smoke-Test Runbook

1. **Health & Checkpointer check:**
   ```bash
   curl -fsS https://<api-host>/api/v2/health
   # Expect durable_thread_persistence=true and checkpointer_mode="postgres" in production
   ```
2. **Verify `note.ingested` -> Provenance Insight loop:**
   - Ingest a test note (`POST /api/v2/ingest` with `skip_review=true`) or enqueue explicitly (`POST /api/v2/agent/triggers/note-ingested`).
   - Confirm `agent-worker` logs completion and `GET /api/v2/agent/runs` shows `status="completed"` with non-zero token counts and `provenance.validate_proposed_bridges` counts.
   - Confirm `GET /api/v2/agent/feed-cards` returns the active card with verbatim `source_quotes` matching chunk text.
3. **Crash-Recovery Drill:**
   - Kill `agent-worker` mid-job (`SIGKILL`), wait past `lease_seconds=300`, restart `agent-worker`, and verify the second worker reclaims the job (`attempts=2`) without losing the task.
