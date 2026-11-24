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

### Backend behaviour the client works around (tracked in the PR #3 review)

- **Questions that never finish.** Questions can stay `queued` or `claimed` forever. The backend has no sweeper for passed `expires_at` or for exhausted `attempts`. The client:
  - stops polling after 15 minutes and shows **Check again** and **Cancel**;
  - treats a non-terminal request past `expires_at` as expired;
  - handles `failed`, `expired` and `cancelled`;
  - decodes any future status as `.unknown`.
- **Timestamps.** Bridge rows serialize datetimes as Python `str()` values like `2026-11-24 06:11:07.650030+00:00`, which the shared ISO-8601 decoder rejects. The bridge models keep these as strings and parse them with `AgentBridgeDate.parse`.
- **Citation URLs.** These are not validated server-side (`Citation.url`), so the client gate is the only defense right now.

## Verification so far

- **No Xcode build or Simulator run yet.** The box is Linux, so nothing here has been compiled for iOS.
- **Syntax check.** `swiftc -parse -swift-version 6` (Swift 6.0.3 on Linux) passes on all 17 new or changed Swift files.
- **Unit tests on Linux.** The networking, model and `AgentAskStore` files were type-checked and tested on Linux with a throwaway SwiftPM package (Foundation, Observation and XCTest), using a `FoundationNetworking` shim. All 10 tests in `AgentBridgeURLTests` pass. SwiftUI files cannot be type-checked on Linux.
- **Xcode project.** `project.pbxproj` was edited by hand to add the 8 app sources and a `Features/AgentBridge` group, then checked with the `pbxproj` Python parser. Running `xcodegen` from `project.yml` also picks them up, because sources are folder-based.

## TODO (next coding agent)

1. **Build in Xcode** (iOS 26 SDK) and fix any type errors. Areas most likely to need attention:
   - `@Observable` singletons held in `@State`;
   - `Text(... format: .relative(...))`;
   - `UIPasteboard.setItems` options;
   - the `GRChip` and `GRButtonStyle` labels.
2. **Add a `GraphRecallTests` unit-test target** to `project.yml`, and add `ios/GraphRecallTests/AgentBridgeURLTests.swift` to it.
3. **Record a "done" interaction for agent cards.** The "Done" chip on a feed agent card currently only advances the feed. It needs a backend seen/dismiss interaction (backend TODO in `feed_integration.py`).
4. **Replace polling with SSE.** Use `GET /requests/{id}/stream` through `ChatSSEClient`, or push notifications when an answer lands (backend TODO in `tools.submit_answer`).
5. **Show agent answers in chat history.** They currently live only in `AgentAskStore`, are restored by id from UserDefaults, and are not scoped to a conversation.
6. **Offer "Ask my agent" automatically.** When the in-app assistant can't answer well, offer the hand-off (backend chat-graph TODO).
7. **Use a real capability flag.** Replace the `/keys` probe with something like a `features.agent_bridge` field on `/auth/profile` or `/health`.
8. **Add more previews and features.** Inbox empty and error states, a digest header card (`schedule_daily_digest`), and an optional "auto-approve from this key" setting.
9. **Accessibility pass.** Dynamic Type at the largest sizes, VoiceOver order in the answer bubble, and UI tests that use the `agent.*` and `chat.askAgent` identifiers.
10. **Show the MCP endpoint correctly.** The keys sheet shows `<base>/mcp/agent`. Confirm whether the deployed mount needs the trailing slash (`/mcp/agent/`), which is what Bot 2's end-to-end test used.
