# Skills over MCP

The agent bridge (`/mcp/agent`) serves [Agent Skills](https://agentskills.io/specification) over
MCP with the `io.modelcontextprotocol/skills` extension (protocol revision 2026-07-28). Clients
that support it list them next to the tools; Claude Code shows them as `/<server>:<skill>`, for
example `/graphrecall:teach-at-my-level`.

A skill carries the multi-step workflow the bridge's tools only make sense inside. Tool
descriptions can say what a tool does, but not "claim, research, then submit, and report an error
rather than leaving the claim to expire".

## The skills

| Skill | Needs key scopes | What it does |
|---|---|---|
| `teach-at-my-level` | `read:knowledge` | `get_knowledge_frontier` for the concepts a question depends on, then teach, refresh or assume each one. Records exposure afterwards if the key can write. |
| `quiz-due-reviews` | `read:knowledge` | A chat quiz on `list_due_reviews`, one recall question at a time. It says plainly that a chat quiz doesn't move the review schedule. |
| `answer-app-questions` | `bridge:answer`, `read:knowledge` | The `list_pending_questions` → `claim_question` → research → `submit_answer` loop. Submits an `error` when it can't answer. |
| `curate-my-feed` | `read:knowledge`, `write:feed` | Aims at the user's frontier, then `propose_feed_items` with idempotency keys, an optional `schedule_daily_digest`, and `suggest_for_later`. |
| `save-learning-session` | `read:knowledge`, `write:ingest` | Distils the conversation into topic, learned, struggled (with why), key details and resources; previews it, then calls `save_learning_session`, which runs as a background task ([TASKS.md](TASKS.md)). |

The files live in `backend/agent_bridge/skill_files/<name>/SKILL.md`. Each one's frontmatter
`metadata.graphrecall-scopes` lists the scopes it needs. **A key only lists, gets or reads the
skills it can run**, so a read-only key never sees a skill that would fail on a write tool. The
listing differs per key, which is why responses say `cacheScope: "private"`.

## Wire format

- `server/discover` advertises `resources` plus `extensions["io.modelcontextprotocol/skills"]`
  (no `directoryRead`).
- `skills/list` returns `{resultType: "complete", skills: [{uri, frontmatter, resources: [{uri,
  digest, size}]}], ttlMs: 300000, cacheScope: "private"}`.
- `skills/get {uri}` returns the same envelope, with the entry under `skill`.
- Files are fetched with `resources/read` at `skill://<name>/<path>`. The digest is the SHA-256 of
  the exact bytes served.
- An unknown skill, an unknown file, path traversal, or a skill the key can't see all return
  JSON-RPC `-32602`.

Code: `backend/agent_bridge/skills.py` (loader, validation, scope filter) and
`add_skills_extension` in `backend/agent_bridge/mcp_app.py`. This needs the `mcp` 2.x low-level
server. On the 1.x code path the bridge serves tools only, as before.

## Adding a skill

1. Create `skill_files/<name>/SKILL.md`. The `name` must be lowercase with hyphens, at most 64
   characters, and equal to the directory name. The `description` (1–1024 characters) says what it
   does and when to use it.
2. Set `metadata.graphrecall-scopes` to every scope its steps need. For steps that are optional,
   write "if the tool is available" rather than adding the scope.
3. Name only tools the bridge actually has, with their real argument names.
4. Keep each file under 100 KB and each skill under 400 KB (Claude Code's limits).
5. Run `pytest backend/tests/test_agent_bridge_skills.py`.

## Client support

- Claude Code: needs v2.1.331 or later, a direct connection to Anthropic, and a supported model.
  Not available in `claude -p`, cloud sessions, GitHub Actions or the Agent SDK.
- Skills over MCP is a public beta in Claude.
- Other clients ignore the extension and keep using the tools.

## Verified

- `backend/tests/test_agent_bridge_skills.py` covers loading, manifests and scope filtering, plus
  an end-to-end run through the official SDK client in-process.
- Live over HTTP against `/mcp/agent` with temporary keys on the showcase account, since revoked and
  deleted:
  - A read-only key listed 2 skills and an all-scopes key listed 4.
  - `skills/get` and `resources/read` matched the manifest digest.
  - A read-only request for `curate-my-feed` returned `-32602`.
  - `tools/list` still returned all 15 tools.
- Not yet checked inside Claude Code itself: the local `claude` is 2.1.263, older than the 2.1.331
  that MCP skills need.
