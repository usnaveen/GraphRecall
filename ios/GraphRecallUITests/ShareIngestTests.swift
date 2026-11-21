import XCTest

/// Verifies automatic Share-Sheet inbox draining onto `POST /api/v2/ingest/url` and surfacing
/// Substack paywall warnings from `IngestResponse.warnings`.
@MainActor
final class ShareIngestTests: XCTestCase {
    override func setUp() async throws {
        continueAfterFailure = false
    }

    func testSeededSubstackURLDrainsAndDisplaysPaywallWarning() {
        let app = XCUIApplication()
        let apiBase = ProcessInfo.processInfo.environment["GR_TEST_STUB_URL"] ?? "http://127.0.0.1:18999"
        app.launchEnvironment["GR_TAB"] = "create"
        app.launchEnvironment["GRAPHRECALL_API_BASE"] = apiBase
        app.launchEnvironment["GR_SEED_SHARE_URL"] = "https://example.substack.com/p/test-post"
        app.launch()

        let warningPredicate = NSPredicate(format: "label CONTAINS[c] %@", "paywalled preview")
        let warningElement = app.staticTexts.matching(warningPredicate).firstMatch
        XCTAssertTrue(
            warningElement.waitForExistence(timeout: 20),
            "Expected Substack paywall warning from /api/v2/ingest/url stub response"
        )
    }
}
