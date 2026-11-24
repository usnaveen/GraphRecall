# GraphRecall production runbook

One VPS (Hetzner CPX31, 4 vCPU / 8 GB, Ubuntu 24.04) running `deploy/compose.prod.yml`:

| Service | Role | Memory cap |
|---|---|---|
| `caddy` | HTTPS (Let's Encrypt) | 160 MB |
| `api` | FastAPI, 2 workers | 1.5 GB |
| `agent-worker` | always-on agent | 768 MB |
| `postgres` | pgvector, PG 17 | 2 GB |
| `neo4j` | 5 Community + APOC | 2.5 GB |
| `migrate` | one-shot, runs before api/worker | — |

Backups go nightly to Cloudflare R2, and a CI restore drill runs every week. Chosen with Gemini in `agent-collab/messages/033–035`.

## First deploy (about an hour, mostly waiting on DNS)

**What the user creates and pays for:**
1. A Hetzner CPX31 with your SSH key.
2. A domain, with an `A` record for `api.<domain>` pointing at the server.
3. Two Cloudflare R2 buckets: `graphrecall-uploads` and `graphrecall-backups`. Add a **14-day lifecycle rule** on the backups bucket, and create access keys.
4. GitHub repository secrets `DEPLOY_HOST` and `DEPLOY_SSH_KEY`, and a `production` environment (add yourself as required reviewer, so each deploy waits for your approval).
5. **Sign in with Apple** (Apple Developer account): enable the capability on the App ID `com.usnaveen.graphrecall`, then create a key with "Sign in with Apple" under Certificates, IDs & Profiles > Keys. Put its Key ID, your Team ID and the `.p8` contents in `APPLE_KEY_ID`, `APPLE_TEAM_ID` and `APPLE_PRIVATE_KEY`. Without them, account deletion can't revoke Apple tokens (App Store guideline 5.1.1(v)), and the API refuses to start with Apple sign-in on.
6. `SESSION_SECRET`: `openssl rand -base64 48`. It signs session tokens; never rotate it casually (see `env.prod.example`).

**Then run:**

```bash
ssh root@<ip> 'bash -s' < deploy/bootstrap.sh
scp deploy/compose.prod.yml deploy/Caddyfile deploy/backup.sh deploy/restore.sh deploy@<ip>:/opt/graphrecall/
scp deploy/env.prod.example deploy@<ip>:/opt/graphrecall/.env      # then edit it on the server
ssh deploy@<ip> 'nano /opt/graphrecall/.env'                        # long random DB passwords, keys, domain
git tag v1.0.0 && git push origin v1.0.0                           # CI tests, builds, deploys
curl -fsS https://api.<domain>/api/v2/health
```

The API refuses to start with unsafe or missing settings (`backend/config/production.py`), or with migrations pending.

## Routine operations

| Task | Command (on the server, in `/opt/graphrecall`) |
|---|---|
| Status | `docker compose -f compose.prod.yml --env-file .env ps` |
| Logs | `docker compose -f compose.prod.yml --env-file .env logs -f --tail 200 api agent-worker` |
| Deploy a version | push a `v*` tag (GitHub Actions), or `GRAPHRECALL_IMAGE=…:vX docker compose … up -d` |
| Roll back | set `GRAPHRECALL_IMAGE` in `.env` to the previous tag, then `up -d`. Migrations are forward-only: roll back code only to versions that work with the newer schema, or restore a backup |
| Migration status | `docker compose … run --rm migrate python -m backend.db.migrate --status` |
| Backup now | `set -a; . .env; set +a; ./backup.sh` |
| Restore | `./restore.sh <stamp>` or `./restore.sh latest`. It asks you to type the stamp to confirm |
| Disk | `df -h /` and `docker system df`. Images are pruned weekly by `docker image prune -af --filter until=168h` (add to cron) |

## Backups and restores

- **What runs:** `backup.sh` at 03:00 UTC (`/etc/cron.d/graphrecall-backup`). It takes an online `pg_dump -Fc`, then an offline `neo4j-admin database dump`, which pauses Neo4j for well under a minute. It writes SHA-256 checksums and uploads to `r2://graphrecall-backups/backups/<stamp>/`.
- **Retention:** the R2 lifecycle rule (14 days).
- **Proof that restores work:** `.github/workflows/restore-drill.yml` runs every Monday and on every change to `deploy/`. It seeds data, backs up, destroys the data, restores, and fails unless every row, node and relationship came back.

## Auth model
- Clients sign in with Apple (`POST /auth/apple`) or Google (`POST /auth/session/google`) and get a 1-hour access token plus a 60-day rotating refresh token (`backend/auth/sessions.py`). Google ID tokens are still accepted as bearers, for older builds.
- **Sign everyone out:** `DELETE FROM auth_refresh_tokens;`. Access tokens die within the hour; rotate `SESSION_SECRET` to end them immediately.
- **Sign one user out:** `UPDATE auth_refresh_tokens SET revoked_at = NOW() WHERE user_id = '<uuid>';`

## Account deletion: what is removed, and what isn't

`DELETE /api/users/me` (App Store guideline 5.1.1(v)) runs `services/account_deletion.py`:

| Store | What happens |
|---|---|
| Postgres | The `users` row, and every user-owned table, which cascades from it |
| Neo4j | Every node with the user's `user_id` (concepts, note sources, graphs) |
| R2 | Every object under `uploads/{user_id}/`, including ones no row references any more |
| LangGraph checkpoints | Every `chat:{user_id}:*` and `ingest:{user_id}:*` thread: full chat history, retrieved note text, ingestion state |
| Sign in with Apple | The Apple authorization is revoked (when the `.p8` key is configured) |
| **Backups** | **Not rewritten.** Nightly dumps in R2 keep deleted data until the 14-day lifecycle rule expires them. The privacy policy must say so. |
| Third parties | Text already sent to Gemini (and topics sent to Tavily) is governed by their retention terms. Use the paid Gemini tier, which doesn't train on prompts. |

Deleting a single note also deletes its chunk images and every concept that only that note explained. Deleting a conversation also deletes its checkpoint thread.

## Incidents

- **API won't start:** `docker compose … logs api`. Most often it's a refused production setting (the log lists them) or a pending migration (run `migrate`).
- **Agent jobs stuck in `running`:** the worker's lease (300 s) reclaims them automatically after a crash. Check the `agent_runs` and `agent_jobs` tables.
- **Out of memory:** each service has a cap, so one bad process can't take the box down. If Neo4j hits its cap during a bulk ingest, raise its page cache in `compose.prod.yml` and lower Postgres's `shared_buffers`, or ingest in batches.
- **Gemini quota or billing errors:** ingests report `completed_missing_embeddings` and retry. `POST /api/v2/ingest/notes/{id}/reembed` retries on demand.

## Moving off the single box later
`DATABASE_URL` and `NEO4J_URI` are the only couplings:
- **Neon:** restore `postgres.dump` with `pg_restore`.
- **AuraDB:** `neo4j-admin database upload`.
- Then remove those services from the compose file.
