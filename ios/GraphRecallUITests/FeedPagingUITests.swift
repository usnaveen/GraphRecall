import XCTest

/// The reel must still page when the swipe starts on a card's content: each card now has its own
/// inner scroll area (for long content) inside the paging scroll view.
@MainActor
final class FeedPagingUITests: XCTestCase {
    override func setUp() async throws {
        continueAfterFailure = false
    }

    private func visibleTexts(_ app: XCUIApplication) -> Set<String> {
        Set(app.staticTexts.allElementsBoundByIndex
            .filter { $0.exists && $0.isHittable && !$0.label.isEmpty }
            .map(\.label))
    }

    func testSwipeOnCardContentPagesToTheNextCard() {
        let app = XCUIApplication()
        app.launchEnvironment["GR_TAB"] = "feed"
        app.launchEnvironment["GR_UITEST"] = "1"
        app.launch()

        XCTAssertTrue(app.buttons["Agent Inbox"].waitForExistence(timeout: 20), "Feed never appeared")
        sleep(2)
        let before = visibleTexts(app)
        XCTAssertFalse(before.isEmpty, "No card text visible")

        // Swipe up starting in the middle of the card's content area.
        let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.35, dy: 0.62))
        let end = app.coordinate(withNormalizedOffset: CGVector(dx: 0.35, dy: 0.18))
        start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .fast, thenHoldForDuration: 0)
        sleep(2)
        let after = visibleTexts(app)

        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = "AfterSwipe"
        shot.lifetime = .keepAlways
        add(shot)

        let kept = before.intersection(after).subtracting(["Feed", "Graph", "Assistant", "Profile", "Create"])
        print("PAGING_BEFORE=\(before.count) AFTER=\(after.count) KEPT=\(kept.sorted())")
        XCTAssertNotEqual(before, after, "Swiping up on card content did not move to the next card")
    }
}
