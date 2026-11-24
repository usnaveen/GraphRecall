import XCTest
#if canImport(GraphRecall)
@testable import GraphRecall
#endif

/// Unit tests for the agent-bridge link gate, date parsing, feed-type fallback and polling policy.
/// TODO(agent-bridge-ios): add a `GraphRecallTests` unit-test target to project.yml (only UI tests
/// exist today). These also run on Linux by compiling them together with the model files
/// (see docs/AGENT_BRIDGE_IOS.md → Verification).
final class AgentBridgeURLTests: XCTestCase {
    func testAllowsHTTPAndHTTPS() {
        XCTAssertNotNil(AgentBridgeURL.safe("https://arxiv.org/abs/2106.09685"))
        XCTAssertNotNil(AgentBridgeURL.safe("http://example.com/a?b=c#d"))
        XCTAssertNotNil(AgentBridgeURL.safe("  HTTPS://Example.com/x  "))
    }

    func testRejectsDangerousSchemes() {
        for raw in [
            "javascript:alert(1)", "JavaScript:alert(document.cookie)", " javascript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD4=", "file:///etc/passwd", "tel:+15555555555",
            "graphrecall://review", "grsource://1", "vbscript:msgbox", "ftp://example.com/x",
        ] {
            XCTAssertNil(AgentBridgeURL.safe(raw), raw)
        }
    }

    func testRejectsMalformedAndSpoofing() {
        for raw in [
            "", "   ", "example.com", "//example.com/x", "https://", "https:///path",
            "https://good.com@evil.com/", "https://user:pass@example.com/",
            "https://exa mple.com", "https://example.com/\u{0000}", "https://example.com/\n/x",
            "https://example.com/" + String(repeating: "a", count: 3000),
        ] {
            XCTAssertNil(AgentBridgeURL.safe(raw), raw.debugDescription)
        }
        XCTAssertNil(AgentBridgeURL.safe(nil))
    }

    func testDisplayHost() {
        XCTAssertEqual(AgentBridgeURL.displayHost(AgentBridgeURL.safe("https://www.Substack.com/p/x")), "substack.com")
    }

    func testCitationAndCardUseTheGate() {
        XCTAssertNil(AgentCitation(title: "x", url: "javascript:alert(1)").safeURL)
        XCTAssertNotNil(AgentCitation(title: "x", url: "https://a.com").safeURL)
        let item = AgentFeedItem(id: "1", title: "t", summary: "s", reason: "r", sourceUrl: "data:text/html,hi")
        XCTAssertNil(item.safeSourceURL)
    }

    func testPythonDatesParse() {
        XCTAssertNotNil(AgentBridgeDate.parse("2026-11-24 06:11:07.650030+00:00"))
        XCTAssertNotNil(AgentBridgeDate.parse("2026-11-24T06:11:07.650030+00:00"))
        XCTAssertNotNil(AgentBridgeDate.parse("2026-11-24T06:11:07Z"))
        XCTAssertNotNil(AgentBridgeDate.parse("2026-11-24"))
        XCTAssertNil(AgentBridgeDate.parse("not a date"))
    }

    func testUnknownFeedTypeDecodesAsUnknown() throws {
        let json = #"{"id":"x","item_type":"hologram","content":{}}"#.data(using: .utf8)!
        let item = try JSONDecoder().decode(FeedItem.self, from: json)
        XCTAssertEqual(item.itemType, .unknown)
        let agent = #"{"id":"agent:1","item_type":"agent_curated","content":{"title":"T"}}"#.data(using: .utf8)!
        XCTAssertEqual(try JSONDecoder().decode(FeedItem.self, from: agent).itemType, .agentCurated)
        // Local lenient parsing keeps the old behaviour for chat/dump cards.
        XCTAssertEqual(FeedItemType.parse("hologram"), .flashcard)
    }

    func testRequestDecodesBridgeRow() throws {
        let json = #"""
        {"id":"e9","status":"answered","question":"q","conversation_id":null,
         "created_at":"2026-11-24 06:11:07.650030+00:00","claimed_at":null,"answered_at":null,
         "answer_text":"**a**","answer_json":{"citations":[{"url":"javascript:x","title":"bad"}]},
         "error":null,"expires_at":"2026-11-26 06:11:07.649585+00:00"}
        """#.data(using: .utf8)!
        let req = try JSONDecoder().decode(AgentRequest.self, from: json)
        XCTAssertEqual(req.status, .answered)
        XCTAssertEqual(req.citations.count, 1)
        XCTAssertNil(req.citations[0].safeURL)
        XCTAssertNotNil(req.expiry)
        let odd = #"{"id":"z","status":"zombie","question":"q"}"#.data(using: .utf8)!
        XCTAssertEqual(try JSONDecoder().decode(AgentRequest.self, from: odd).status, .unknown)
    }

    @MainActor
    func testStaleQueuedRequestIsTreatedAsExpired() async {
        let past = AgentRequest(id: "1", status: .queued, question: "q", expiresAt: "2020-01-01 00:00:00+00:00")
        XCTAssertNotEqual(AgentAskStore.phase(for: past), .waiting)
        let live = AgentRequest(id: "2", status: .claimed, question: "q", expiresAt: "2999-01-01 00:00:00+00:00")
        XCTAssertEqual(AgentAskStore.phase(for: live), .waiting)
        XCTAssertEqual(AgentAskStore.phase(for: AgentRequest(id: "3", status: .expired, question: "q")),
                       .failed(AgentRequestStatus.expired.label))
        XCTAssertEqual(AgentAskStore.pollInterval(elapsed: 5), 3)
        XCTAssertEqual(AgentAskStore.pollInterval(elapsed: 120), 10)
        XCTAssertEqual(AgentAskStore.pollInterval(elapsed: 900), 30)
    }

    @MainActor
    func testPollingTimesOutClientSide() async throws {
        // Server that never finishes (backend has no sweeper): store must stop on its own.
        let neverDone = AgentAskTransport(
            create: { q, _, _ in AgentRequest(id: "s1", status: .queued, question: q) },
            fetch: { id in AgentRequest(id: id, status: .claimed, question: "q") },
            cancel: { id in AgentRequest(id: id, status: .cancelled, question: "q") }
        )
        let store = AgentAskStore(transport: neverDone, clientTimeout: 0.5)
        store.ask("hello", conversationId: nil)
        for _ in 0..<50 where store.tracked.first?.phase != .timedOut {
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertEqual(store.tracked.first?.phase, .timedOut)
        store.dismiss(store.tracked[0].id)
    }
}

/// Contract checks against PR #3 @ cadf9c8 (ISO timestamps, 400/409/429/503 copy, swept statuses).
final class AgentBridgeContractTests: XCTestCase {
    func testISODatesFromSerializationDecode() throws {
        for raw in ["2026-11-24T06:11:10.751395+00:00", "2026-11-24T06:11:10+00:00",
                    "2026-11-24T06:11:10Z", "2026-11-24T11:41:10.751+05:30", "2026-11-24"] {
            XCTAssertNotNil(AgentBridgeDate.parse(raw), raw)
        }
        let a = AgentBridgeDate.parse("2026-11-24T06:11:10.751395+00:00")!
        let b = AgentBridgeDate.parse("2026-11-24 06:11:10.751395+00:00")!   // legacy fallback
        XCTAssertEqual(a.timeIntervalSince1970, b.timeIntervalSince1970, accuracy: 0.001)
        XCTAssertEqual(AgentBridgeDate.parse("2026-11-24T11:41:10+05:30")!.timeIntervalSince1970,
                       AgentBridgeDate.parse("2026-11-24T06:11:10Z")!.timeIntervalSince1970, accuracy: 0.001)
    }

    func testFeedItemRowDecodes() throws {
        let json = #"""
        {"item":{"id":"8596a94b-80bc-4377-b240-14f9960e25fa","user_id":"u","key_id":"k","status":"approved",
         "item_kind":"article","title":"Attention paper","summary":"s","body_json":{},
         "source_url":"https://example.com/paper","source_kind":"web","reason":"exam","concept_ids":["cA1"],
         "target_date":"2026-11-24","dedupe_key":"x","idempotency_key":null,
         "created_at":"2026-11-24T06:11:06.123456+00:00","reviewed_at":"2026-11-24T06:11:07+00:00"}}
        """#.data(using: .utf8)!
        let item = try JSONDecoder().decode(AgentFeedItemEnvelope.self, from: json).item
        XCTAssertEqual(item.status, .approved)
        XCTAssertNotNil(item.target)
        XCTAssertNotNil(AgentBridgeDate.parse(item.createdAt))
    }

    func testAuditDecodes() throws {
        let json = #"{"events":[{"id":"1","user_id":"u","key_id":null,"actor":"agent","action":"tool_call","tool":"propose_feed_items","target_id":null,"details":{"created":2},"created_at":"2026-11-24T06:11:06+00:00"}]}"#.data(using: .utf8)!
        let ev = try JSONDecoder().decode(AgentAuditResponse.self, from: json).events[0]
        XCTAssertEqual(ev.tool, "propose_feed_items")
        XCTAssertNotNil(ev.created)
    }

    private func http(_ code: Int, _ detail: String) -> Error {
        APIError.http(code, #"{"detail":"\#(detail)"}"#)
    }

    func testFriendlyCopy() {
        let rate = AgentBridgeErrorCopy.message(http(429, "Too many questions for your agent; try later"), action: .ask)
        XCTAssertTrue(rate.contains("10 minutes"), rate)
        XCTAssertTrue(AgentBridgeErrorCopy.isRateLimited(http(429, "x")))
        XCTAssertTrue(AgentBridgeErrorCopy.message(http(409, "Invalid transition"), action: .approve).contains("Already handled"))
        XCTAssertTrue(AgentBridgeErrorCopy.message(http(409, "Too many active agent keys"), action: .createKey).contains("5 active keys"))
        XCTAssertTrue(AgentBridgeErrorCopy.message(http(503, "Agent keys are not configured on this server"), action: .createKey).contains("aren\u{2019}t set up"))
        XCTAssertTrue(AgentBridgeErrorCopy.message(http(409, "Daily cap of 50 pending suggestions reached"), action: .approve).contains("limit"))
        XCTAssertFalse(AgentBridgeErrorCopy.message(http(400, "request_id must be a UUID"), action: .load).contains("UUID"))
        XCTAssertTrue(AgentBridgeErrorCopy.isConversationNotFound(http(404, "Conversation not found")))
        XCTAssertFalse(AgentBridgeErrorCopy.isConversationNotFound(http(404, "Request not found")))
    }

    @MainActor
    func testSweptStatusesUseServerReason() async {
        let expired = AgentRequest(id: "1", status: .expired, question: "q", error: "Expired before an agent answered")
        XCTAssertEqual(AgentAskStore.phase(for: expired), .failed("Expired before an agent answered"))
        let failed = AgentRequest(id: "2", status: .failed, question: "q", error: "No agent finished it after 3 attempts")
        XCTAssertEqual(AgentAskStore.phase(for: failed), .failed("No agent finished it after 3 attempts"))
    }

    @MainActor
    func testRateLimitedAskShowsFriendlyCopyAndRetries() async throws {
        final class Counter: @unchecked Sendable { var n = 0 }
        let calls = Counter()
        let transport = AgentAskTransport(
            create: { q, _, _ in
                calls.n += 1
                if calls.n == 1 { throw APIError.http(429, #"{"detail":"Too many questions"}"#) }
                return AgentRequest(id: "s1", status: .answered, question: q, answerText: "ok")
            },
            fetch: { id in AgentRequest(id: id, status: .answered, question: "q", answerText: "ok") },
            cancel: { id in AgentRequest(id: id, status: .cancelled, question: "q") }
        )
        let store = AgentAskStore(transport: transport, clientTimeout: 5)
        store.ask("hello", conversationId: nil)
        for _ in 0..<20 { if case .sendFailed = store.tracked[0].phase { break }; try await Task.sleep(for: .milliseconds(50)) }
        guard case let .sendFailed(msg) = store.tracked[0].phase else { return XCTFail("expected sendFailed") }
        XCTAssertTrue(msg.contains("10 minutes"))
        store.retrySend(store.tracked[0].id)
        for _ in 0..<40 where store.tracked[0].phase != .answered { try await Task.sleep(for: .milliseconds(100)) }
        XCTAssertEqual(store.tracked[0].phase, .answered)
        XCTAssertEqual(calls.n, 2)
        store.stopAll()
    }

    @MainActor
    func testConversationNotFoundRetriesWithoutConversation() async throws {
        final class Seen: @unchecked Sendable { var convs: [String?] = [] }
        let seen = Seen()
        let transport = AgentAskTransport(
            create: { q, conv, _ in
                seen.convs.append(conv)
                if conv != nil { throw APIError.http(404, #"{"detail":"Conversation not found"}"#) }
                return AgentRequest(id: "s2", status: .queued, question: q)
            },
            fetch: { id in AgentRequest(id: id, status: .answered, question: "q", answerText: "ok") },
            cancel: { id in AgentRequest(id: id, status: .cancelled, question: "q") }
        )
        let store = AgentAskStore(transport: transport, clientTimeout: 10)
        store.ask("hi", conversationId: "11111111-1111-1111-1111-111111111111")
        for _ in 0..<20 where store.tracked[0].serverId == nil { try await Task.sleep(for: .milliseconds(50)) }
        XCTAssertEqual(store.tracked[0].serverId, "s2")
        XCTAssertEqual(seen.convs.count, 2)
        XCTAssertNil(seen.convs[1] ?? nil)
        store.stopAll()
    }
}
