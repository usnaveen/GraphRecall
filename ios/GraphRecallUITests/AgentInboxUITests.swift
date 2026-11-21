import XCTest

/// Verifies the native Liquid Glass Agent Inbox sheet inside the Feed tab against offline demo data.
@MainActor
final class AgentInboxUITests: XCTestCase {
    override func setUp() async throws {
        continueAfterFailure = false
    }

    func testAgentInboxSheetOpensDisplaysQuotesAndDismisses() {
        let app = XCUIApplication()
        app.launchEnvironment["GR_TAB"] = "feed"
        app.launchEnvironment["GR_UITEST"] = "1"
        app.launch()

        let inboxButton = app.buttons["Agent Inbox"]
        XCTAssertTrue(inboxButton.waitForExistence(timeout: 20), "Agent Inbox button never appeared on Feed")

        let feedShot = XCUIScreen.main.screenshot()
        print("FEED_SCREENSHOT_SIZE=\(feedShot.image.size)")
        let feedAttach = XCTAttachment(screenshot: feedShot)
        feedAttach.name = "FeedScreen"
        feedAttach.lifetime = .keepAlways
        add(feedAttach)

        inboxButton.tap()

        XCTAssertTrue(app.navigationBars["Agent Inbox"].waitForExistence(timeout: 10), "Agent Inbox navigation bar did not appear")
        XCTAssertTrue(app.staticTexts["GROUNDED IN YOUR NOTES"].firstMatch.waitForExistence(timeout: 10)
            || app.staticTexts["Grounded in your notes"].firstMatch.waitForExistence(timeout: 5),
            "Provenance quote header missing in Agent Inbox")
        XCTAssertTrue(app.buttons["Ask Assistant"].firstMatch.exists, "Ask Assistant action missing")
        XCTAssertTrue(app.buttons["Dismiss"].firstMatch.exists, "Dismiss action missing")

        let inboxShot = XCUIScreen.main.screenshot()
        print("INBOX_SCREENSHOT_SIZE=\(inboxShot.image.size)")
        let inboxAttach = XCTAttachment(screenshot: inboxShot)
        inboxAttach.name = "AgentInboxSheet"
        inboxAttach.lifetime = .keepAlways
        add(inboxAttach)

        app.buttons["Dismiss"].firstMatch.tap()
        XCTAssertTrue(
            app.staticTexts["Revisit the 2/L step-size bound before next quiz"].waitForExistence(timeout: 5),
            "Remaining demo insight card did not stay visible after dismissing first card"
        )
    }
}
