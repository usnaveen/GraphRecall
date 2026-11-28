# Background ingest (MCP Tasks)

Two bridge tools write straight into the user's knowledge graph. They take from 20 seconds to
several minutes, so they run as background jobs, using the MCP Tasks extension
(`io.modelcontextprotocol/tasks`, protocol revision 2026-07-28).

| Tool | What it does |
|---|---|
| `ingest_link` | Imports one article, blog post or paper page, the same way the app's Import link does. |
| `save_learning_session` | Saves a learning session (described below). |
| `get_ingest_status` | Returns an import's state, for clients that don't track MCP tasks themselves. |

All three need the new key scope **`write:ingest`**. Existing keys don't have it; the user has to
create a key with it, or approve it on the OAuth consent screen ("Add to Your Knowledge Graph").
Unlike `write:feed`, nothing waits for approval in the app. Each note is labelled as saved by the
user's agent, every call is audited, and each import counts against the user's normal daily ingest
quota.

## save_learning_session

This is meant for the end of a session where the user learned something with Claude. The agent
sends:

- `topic`
- `summary_markdown`: the key details, written in the agent's own words
- `learned`: concepts the user showed they understood
- `struggled`: concepts the user found hard, each as `{concept, why}`
- `resources`: up to 15, each as `{url, title, note}`
- `transcript`: optional raw chat, cut at 30,000 characters

The job then runs these steps:

1. **Writes one session note.** The note has sections for what was learned, what was hard, the key
   details and the resources, and goes through the normal ingestion pipeline (concepts, flashcards,
   search). It is stored as `resource_type = chat_conversation` and titled "<topic> (learning
   session)".
2. **Imports each resource** one at a time. Duplicates are detected. Video links are listed in the
   note but skipped for now, because video import is on `feat/youtube-ingest` and not yet on this
   branch.
3. **Records knowledge evidence.** Learned concepts get a 0.65 signal and struggles get 0.25, so the
   app reviews the struggles sooner.

The `save-learning-session` skill tells Claude how to distil a conversation into this shape and to
show the user a preview before saving.

## Protocol

- **Client declares the extension in the request's `_meta`.** `tools/call` returns a
  `CreateTaskResult`:

  ```json
  {
    "resultType": "task",
    "taskId": "grt_...",
    "status": "working",
    "statusMessage": "...",
    "createdAt": "...",
    "lastUpdatedAt": "...",
    "ttlMs": 88200000,
    "pollIntervalMs": 5000
  }
  ```

  The row is written before the answer is sent. `tasks/get` returns the same object with
  `resultType: "complete"`, plus `result` when completed or `error` when failed. `statusMessage`
  tracks progress, for example "Reading 2 of 5: ...".
- **Client doesn't declare it.** It never gets a task. The same job starts, the normal result
  carries a `task_id`, and the client polls `get_ingest_status`. Such a client calling `tasks/*`
  gets `-32021`.
- **`tasks/cancel`** stops the job (cooperatively) and acknowledges with `{"resultType":
  "complete"}`. **`tasks/update`** is acknowledged and ignored, because these jobs never ask for
  input.
- **Ids are bound to the user.** Ids are unguessable, and every read checks the owner. An unknown
  id, an expired id and another user's id all return `-32602`.
- **`failed` means a JSON-RPC-level error.** A job that ran but couldn't import some resources is
  `completed`, with per-resource outcomes in `result`. `isError` is set only when nothing was saved.
- **Retention and limits:**
  - Results are kept for 24 hours after the longest possible run (30 minutes); that is the `ttlMs`.
  - A job that stops reporting progress for longer than the longest run (a server restart) is
    reported `failed`, with "interrupted".
  - Each user can have at most 2 imports running at once.

State lives in the `agent_tasks` table (migration `039_agent_tasks.sql`). The work runs as an
asyncio task in the API process. Code is in `backend/agent_bridge/tasks.py` (store, runner, wire
format), `ingest_jobs.py` (the work) and `add_tasks_extension` in `mcp_app.py`.

## Client support

Claude Code polls MCP tasks from v2.1.304. Older clients, and the local `claude` at 2.1.263, take
the `get_ingest_status` path.

## Verified

- `backend/tests/test_agent_bridge_tasks.py`: the runner, cancellation (including before the job
  starts), expired and orphaned tasks, the per-user cap, user binding, the session job, and the
  wire protocol over Streamable HTTP.
- A live run over HTTP on the showcase account with a temporary key. The call answered in 0.1
  seconds, `tasks/get` showed progress, and the job completed in about 30 seconds. It saved the
  session note and the PEP 20 article, skipped the video, and recorded the evidence. Everything it
  created was deleted afterwards, and the key was revoked.
- The first live run found that `notes.resource_type` is CHECK-constrained and doesn't allow
  `learning_session`. `run_ingestion` still returned a `note_id` when storing the note failed. The
  job now uses `chat_conversation` and confirms the note row exists before reporting "imported".
