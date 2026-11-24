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
