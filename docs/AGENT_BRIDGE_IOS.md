# Agent bridge: iOS client (scaffolding)

Branch `feat/agent-bridge-ios`, stacked on `feat/agent-bridge-mcp` (PR #3). It adds the iOS side of
the GraphRecall to external-agent bridge: the approval inbox, agent cards in the feed, "Ask my agent"
in chat, and agent-key settings. Backend contract: `backend/agent_bridge/router.py`.

**Status: scaffolding, roughly 75% done. It has not been compiled with Xcode yet** (see Verification).

## Feature gate

Everything is hidden unless `AgentBridgeCapability.isAvailable` is true. That needs both of these:

1. **Settings → Agent → Connect an agent** is on. It is stored in `graphrecall.agentBridge.enabled` and is off by default.
2. The server has the bridge mounted. The app probes `GET /api/agent-bridge/keys`: a 200 means on, and a 404 means `AGENT_BRIDGE_ENABLED` is unset.

The one exception is approved `agent_curated` items. They are rendered whenever `/api/feed` returns them, because the server only does that when the bridge is on.

## What's done

| Area | Files |
|---|---|
| Wire models and mocks (keys, feed items, requests, lenient date parsing, **shared URL gate**) | `Networking/Models/AgentBridgeModels.swift` |
| REST client for every PR #3 route | `Networking/APIClient+AgentBridge.swift` |
| Feature gate and pending count | `Networking/AgentBridgeCapability.swift` |
| Approval inbox: Pending / Approved / Rejected, approve, reject, approve all, source link, rationale, "From your agent" badge | `Features/AgentBridge/AgentInboxView.swift` |
| Agent card in the feed: badge, summary or flashcard, "why", source host; no SM-2 slider | `Features/AgentBridge/AgentCardViews.swift`, `FeedCardViews.swift`, `FeedContentCard.swift` |
| Feed top-bar inbox button with a pending badge | `FeedView.swift` |
| "Ask my agent": composer button and a chip under an answer, polling, researching state, answer and citations, timeout, retry and cancel | `Features/AgentBridge/AgentAskStore.swift`, `AgentAskViews.swift`, `ChatView.swift` |
| Agent keys: list, create (scopes, expiry, shown once, copied to a local-only clipboard that expires), revoke | `Features/AgentBridge/AgentKeysView.swift`, `SettingsView.swift` |
| Unit tests: URL gate, date parsing, unknown feed type, request decoding, stale-request handling, client timeout | `ios/GraphRecallTests/AgentBridgeURLTests.swift` |

Every new view has a `#Preview` that uses `AgentBridgeMocks`, so no network is needed.

### Safety rules applied to agent content (it is untrusted)

- **Links.** `AgentBridgeURL.safe` is the only gate. It allows only absolute `http`/`https` URLs that have a host and no `user:pass@`, contain no control characters or spaces, and are at most 2048 characters long. Card `source_url`, citation URLs and markdown links in answers all go through it. Anything else is shown as plain text and is never opened. The link shows the real host, such as `substack.com`.
- **Text.** Card title, summary, reason and flashcard text render with `Text(verbatim:)`, so no markdown is interpreted and no links are created.
- **Answers.** These render as inline-only markdown (`AgentMarkdown.render`), and every link that fails the gate is removed. No HTML or images are rendered.
- **Feed types.** Unknown `item_type` values now decode to `FeedItemType.unknown` and are filtered out of the feed. They are no longer silently turned into blank Term Cards. The lenient `FeedItemType.parse` still maps local chat and dump cards to flashcards.
- **Grading.** Agent cards never call `/api/feed/review`, because `agent:<uuid>` is not an SM-2 item.

### Contract with PR #3 @ `cadf9c8` (merged into this branch)

| Backend change | iOS handling |
|---|---|
| Timestamps are ISO 8601 with `T` and an offset; `target_date` is `yyyy-MM-dd` | `AgentBridgeDate.parse` tries ISO first: fractional seconds of any length, `Z` or `±hh:mm`. It still accepts the old `str(datetime)` form as a fallback. Mocks now use ISO. |
| Malformed ids → **400**; an unknown `status=` filter → 400 | Ids are percent-encoded strictly. `.unknown` is never sent as a status filter. A 400 shows generic copy ("update the app"). |
| `conversation_id` must be a UUID the user owns → 400 or **404** | `AgentAskStore` retries once without `conversation_id` when it gets "Conversation not found". |
| `POST /requests` hourly quota → **429** (`Retry-After: 600`) | The bubble says "…try again in about 10 minutes" and shows a **Try again** chip (`retrySend`). |
| Daily caps, such as 50 pending suggestions per day (enforced on the agent side, over MCP) | Any error whose detail mentions a daily cap or limit shows "Your agent hit today's limit". |
| Approving or rejecting an already-handled item → **409** | The inbox shows a toast ("Already handled…") and reloads instead of erroring. |
| `POST /keys` with no pepper configured → **503**; 5 active keys → 409 | Friendly copy in Agent keys. |
| The server sweeps stale questions to `expired` or `failed` and puts the reason in `error` | Both show the server's reason. The 15-minute client timeout and the treat-past-`expires_at`-as-expired check remain as fallbacks. |
| New `GET /audit` | Model and client method `agentAudit()` are done; the UI is a TODO. |
| Citation URLs are validated server-side | The client gate (`AgentBridgeURL.safe`) still applies, as defense in depth. |

All error copy lives in `AgentBridgeErrorCopy` (`AgentBridgeModels.swift`).

## Verification so far

- **No Xcode build or Simulator run yet.** The box is Linux, so nothing here has been compiled for iOS.
- **Syntax check.** `swiftc -parse -swift-version 6` (Swift 6.0.3 on Linux) passes on all 17 new or changed Swift files.
- **Unit tests on Linux.** The networking, model and `AgentAskStore` files were type-checked and tested on Linux with a throwaway SwiftPM package (Foundation, Observation and XCTest), using a `FoundationNetworking` shim. All **17** tests pass: 10 in `AgentBridgeURLTests`, plus 7 in `AgentBridgeContractTests` covering ISO and legacy dates, the feed-item and audit payloads, error copy for 400/409/429/503 and the daily cap, swept statuses, retry after a 429, and retry without a conversation after a 404. SwiftUI files cannot be type-checked on Linux.
- **Xcode project.** `project.pbxproj` was edited by hand to add the 8 app sources and a `Features/AgentBridge` group, then checked with the `pbxproj` Python parser. Running `xcodegen` from `project.yml` also picks them up, because sources are folder-based.

## TODO (next coding agent)

1. ~~**Build in Xcode**~~ Done in the merge into `feat/knowledge-map`: builds with the iOS 26 SDK.
   The only change needed was `GRButtonStyle(kind:)`, which our base replaced with the native
   glass `.grButton(_:fullWidth:compact:)` modifier.
2. **Add a `GraphRecallTests` unit-test target** to `project.yml`, and add `ios/GraphRecallTests/AgentBridgeURLTests.swift` to it.
3. **Record a "done" interaction for agent cards.** The "Done" chip on a feed agent card currently only advances the feed. It needs a backend seen/dismiss interaction (backend TODO in `feed_integration.py`).
4. **Replace polling with SSE.** Use `GET /requests/{id}/stream` through `ChatSSEClient`, or push notifications when an answer lands (backend TODO in `tools.submit_answer`).
5. **Show agent answers in chat history.** They currently live only in `AgentAskStore`, are restored by id from UserDefaults, and are not scoped to a conversation.
6. **Offer "Ask my agent" automatically.** When the in-app assistant can't answer well, offer the hand-off (backend chat-graph TODO).
7. **Add an Activity screen** for `GET /audit` under Agent keys.
8. **Use a real capability flag.** Replace the `/keys` probe with something like a `features.agent_bridge` field on `/auth/profile` or `/health`.
9. **Add more previews and features.** Inbox empty and error states, a digest header card (`schedule_daily_digest`), and an optional "auto-approve from this key" setting.
10. **Accessibility pass.** Dynamic Type at the largest sizes, VoiceOver order in the answer bubble, and UI tests that use the `agent.*` and `chat.askAgent` identifiers.
11. ~~**Show the MCP endpoint correctly.**~~ Done in the merge: the keys sheet now shows `<base>/mcp/agent/`. Without the slash the mount answers 307 to `/mcp/agent/`, which not every MCP client follows with its Authorization header.
