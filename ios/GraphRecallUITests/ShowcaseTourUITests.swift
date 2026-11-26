import XCTest

/// A paced walk through the showcase learner's feed, for screen-recording demo footage
/// (simulated swipes outside XCUITest can't page the reel). Signs in as the fictional
/// showcase account on a local DEBUG backend; skipped unless SHOWCASE_TOUR=1 is set.
@MainActor
final class ShowcaseTourUITests: XCTestCase {
    func testFeedTour() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["SHOWCASE_TOUR"] == "1", "Footage capture only")
        let app = XCUIApplication()
        app.launchEnvironment = [
            "GR_TAB": "feed",
            "GRAPHRECALL_API_BASE": "http://localhost:8001",
            "GR_SEED_ACCESS_TOKEN": "showcase-token",
            "GR_SEED_REFRESH_TOKEN": "showcase-local",
            "GR_SEED_EXPIRES_IN": "2592000",
            "GR_SEED_NAME": "Jordan Avery",
        ]
        app.launch()
        XCTAssertTrue(app.buttons["Agent Inbox"].waitForExistence(timeout: 40), "Feed never appeared")
        sleep(5)

        func nextCard() {
            let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.35, dy: 0.66))
            let end = app.coordinate(withNormalizedOffset: CGVector(dx: 0.35, dy: 0.2))
            start.press(forDuration: 0.04, thenDragTo: end, withVelocity: .fast, thenHoldForDuration: 0)
        }

        nextCard()          // multiple choice
        sleep(3)
        let option = app.buttons.matching(identifier: "review.option").element(boundBy: 0)
        if option.waitForExistence(timeout: 3) {
            option.tap()
            sleep(1)
            let check = app.buttons["Check answer"]
            if check.waitForExistence(timeout: 2) { check.tap() }
            sleep(3)
        }
        for _ in 0..<4 {    // territory, showcase, code sandbox, trade-off duel
            nextCard()
            sleep(4)
        }
    }

    /// Agent inbox, the resume viewer and an Assistant answer, in one run.
    func testFeatureTour() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["SHOWCASE_TOUR"] == "1", "Footage capture only")
        let app = XCUIApplication()
        app.launchEnvironment = [
            "GR_TAB": "feed",
            "GRAPHRECALL_API_BASE": "http://localhost:8001",
            "GR_SEED_ACCESS_TOKEN": "showcase-token",
            "GR_SEED_REFRESH_TOKEN": "showcase-local",
            "GR_SEED_EXPIRES_IN": "2592000",
            "GR_SEED_NAME": "Jordan Avery",
        ]
        app.launch()
        let inbox = app.buttons["Agent Inbox"]
        XCTAssertTrue(inbox.waitForExistence(timeout: 40), "Feed never appeared")
        sleep(4)

        // Agent inbox: suggestions an outside agent sent over MCP.
        inbox.tap()
        sleep(5)
        let sheet = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.62))
        sheet.press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.3)),
                    withVelocity: .slow, thenHoldForDuration: 0.3)
        sleep(3)
        if app.buttons["Done"].exists { app.buttons["Done"].tap() }
        sleep(2)

        // Resume viewer: the PDF with every skill coloured by evidence.
        app.buttons["Profile"].firstMatch.tap()
        sleep(4)
        let resume = app.buttons["Resume"].firstMatch
        if resume.waitForExistence(timeout: 8) { resume.tap() }
        sleep(6)
        let mid = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.78))
        mid.press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.42)),
                  withVelocity: .slow, thenHoldForDuration: 0.5)
        sleep(5)

    }

    /// One suggested question in the Assistant, answered from the learner's graph.
    func testAssistantTour() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["SHOWCASE_TOUR"] == "1", "Footage capture only")
        let app = XCUIApplication()
        app.launchEnvironment = [
            "GR_TAB": "assistant",
            "GRAPHRECALL_API_BASE": "http://localhost:8001",
            "GR_SEED_ACCESS_TOKEN": "showcase-token",
            "GR_SEED_REFRESH_TOKEN": "showcase-local",
            "GR_SEED_EXPIRES_IN": "2592000",
            "GR_SEED_NAME": "Jordan Avery",
        ]
        app.launch()
        let suggestion = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Explain'")).firstMatch
        XCTAssertTrue(suggestion.waitForExistence(timeout: 40), "No suggestions")
        sleep(3)
        suggestion.tap()
        sleep(18)
    }
}
