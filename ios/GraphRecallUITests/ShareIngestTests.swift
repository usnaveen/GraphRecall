import XCTest

/// Verifies Share-Sheet inbox draining onto `POST /api/v2/ingest/url` (paywall warnings,
/// duplicate warnings, 422 readable `detail` messages), single-flight `/auth/refresh` rotation on 401,
/// and Sign in with Apple UI presence.
@MainActor
final class ShareIngestTests: XCTestCase {
    private var stubBaseURL: String {
        ProcessInfo.processInfo.environment["GR_TEST_STUB_URL"] ?? "http://127.0.0.1:18999"
    }

    override func setUp() async throws {
        continueAfterFailure = false
    }

    func testSeededSubstackURLDrainsAndDisplaysPaywallWarning() {
        let app = makeApp(seedURL: "https://example.substack.com/p/test-post")
        app.launch()

        let warningPredicate = NSPredicate(format: "label CONTAINS[c] %@", "paywalled preview")
        let warningElement = app.staticTexts.matching(warningPredicate).firstMatch
        XCTAssertTrue(
            warningElement.waitForExistence(timeout: 20),
            "Expected Substack paywall warning from /api/v2/ingest/url stub response"
        )
    }

    func testDuplicateShareDisplaysAlreadyInLibraryWarning() {
        let app = makeApp(seedURL: "https://example.substack.com/p/duplicate-post")
        app.launch()

        let detailPredicate = NSPredicate(format: "label CONTAINS[c] %@", "already in your library")
        XCTAssertTrue(
            app.staticTexts.matching(detailPredicate).firstMatch.waitForExistence(timeout: 20),
            "Expected duplicate-share warning toast from completed_duplicate stub response"
        )
    }

    func testUnsafeLink422DisplaysReadableDetailWithoutRawJSON() {
        let app = makeApp(seedURL: "http://169.254.169.254/latest")
        app.launch()

        let detailPredicate = NSPredicate(
            format: "label CONTAINS[c] %@",
            "links to private or local network addresses can't be imported"
        )
        XCTAssertTrue(
            app.staticTexts.matching(detailPredicate).firstMatch.waitForExistence(timeout: 20),
            "Expected readable 422 detail string in toast"
        )
        XCTAssertFalse(
            app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "HTTP 422")).firstMatch.exists,
            "Toast leaked raw HTTP 422 prefix instead of extracted detail"
        )
        XCTAssertFalse(
            app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "\"detail\"")).firstMatch.exists,
            "Toast leaked raw JSON payload instead of extracted detail"
        )
    }

    func testExpiredAccessTokenTriggersSingleRefreshAndRetries() async throws {
        try await resetStubStats()

        let app = makeApp(
            seedURL: "https://example.substack.com/p/auth-refresh-post",
            extraEnv: [
                "GR_SEED_ACCESS_TOKEN": "expired-token",
                "GR_SEED_REFRESH_TOKEN": "seed-refresh",
                "GR_SEED_EXPIRES_IN": "3600",
            ]
        )
        app.launch()

        let successPredicate = NSPredicate(format: "label CONTAINS[c] %@", "Added to your knowledge graph")
        XCTAssertTrue(
            app.staticTexts.matching(successPredicate).firstMatch.waitForExistence(timeout: 20),
            "Expected retried ingest to succeed after 401 -> /auth/refresh rotation"
        )

        let stats = try await fetchStubStats()
        XCTAssertEqual(stats.refreshCount, 1, "Expected /auth/refresh to be called exactly once")
        XCTAssertEqual(stats.refreshTokens, ["seed-refresh"])
        XCTAssertEqual(
            stats.ingestCalls.map(\.auth),
            ["Bearer expired-token", "Bearer rotated-access-token"]
        )
    }

    func testWelcomeShowsContinueWithApple() {
        let app = XCUIApplication()
        app.launchArguments = ["-graphrecall.hasOnboarded", "NO"]
        app.launchEnvironment["GR_UITEST"] = "1"
        app.launchEnvironment["GR_RESET_AUTH"] = "1"
        app.launch()

        let appleButton = app.buttons["welcome.appleSignIn"]
        XCTAssertTrue(
            appleButton.waitForExistence(timeout: 15),
            "Continue with Apple button did not appear on WelcomeView"
        )
    }

    // MARK: - Helpers

    private func makeApp(seedURL: String, extraEnv: [String: String] = [:]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["GR_TAB"] = "create"
        app.launchEnvironment["GR_RESET_AUTH"] = "1"
        app.launchEnvironment["GR_RESET_SHARE_INBOX"] = "1"
        app.launchEnvironment["GRAPHRECALL_API_BASE"] = stubBaseURL
        app.launchEnvironment["GR_SEED_SHARE_URL"] = seedURL
        for (k, v) in extraEnv {
            app.launchEnvironment[k] = v
        }
        return app
    }

    private struct StubStats: Decodable {
        struct IngestCall: Decodable {
            let url: String
            let auth: String
        }
        let refreshCount: Int
        let refreshTokens: [String]
        let ingestCalls: [IngestCall]

        enum CodingKeys: String, CodingKey {
            case refreshCount = "refresh_count"
            case refreshTokens = "refresh_tokens"
            case ingestCalls = "ingest_calls"
        }
    }

    private func resetStubStats() async throws {
        var req = URLRequest(url: URL(string: "\(stubBaseURL)/__stub/reset")!)
        req.httpMethod = "POST"
        let (_, resp) = try await URLSession.shared.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? -1
        XCTAssertEqual(code, 200, "Failed to reset stub server stats")
    }

    private func fetchStubStats() async throws -> StubStats {
        let (data, resp) = try await URLSession.shared.data(from: URL(string: "\(stubBaseURL)/__stub/stats")!)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? -1
        XCTAssertEqual(code, 200, "Failed to fetch stub server stats")
        return try JSONDecoder().decode(StubStats.self, from: data)
    }
}
