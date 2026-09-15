import XCTest

/// Drives the Today → review session → summary loop against the offline demo pack.
/// `GR_UITEST` points the API at an unreachable port so the deck is deterministic.
@MainActor
final class ReviewFlowUITests: XCTestCase {
    override func setUp() async throws {
        continueAfterFailure = false
    }

    private func launchToday() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["GR_TAB"] = "feed"
        app.launchEnvironment["GR_UITEST"] = "1"
        app.launch()
        return app
    }

    func testStartReviewOpensSession() {
        let app = launchToday()
        let start = app.buttons["today.startReview"]
        XCTAssertTrue(start.waitForExistence(timeout: 20), "Start review never appeared on Today")
        start.tap()

        XCTAssertTrue(app.buttons["End session"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["review.position"].exists)
    }

    func testEndingSessionReturnsToToday() {
        let app = launchToday()
        let start = app.buttons["today.startReview"]
        XCTAssertTrue(start.waitForExistence(timeout: 20))
        start.tap()

        let end = app.buttons["End session"]
        XCTAssertTrue(end.waitForExistence(timeout: 5))
        end.tap()
        XCTAssertTrue(start.waitForExistence(timeout: 5))
    }

    func testGradingEveryCardShowsSummary() {
        let app = launchToday()
        let start = app.buttons["today.startReview"]
        XCTAssertTrue(start.waitForExistence(timeout: 20))
        start.tap()

        let summaryDone = app.buttons["review.summary.done"]
        var graded = 0
        for _ in 0..<80 {
            if summaryDone.exists { break }

            let grade = app.buttons["review.grade.Good"]
            if grade.exists && grade.isHittable {
                grade.tap()
                graded += 1
                continue
            }
            let reveal = app.buttons["review.reveal"]
            if reveal.exists && reveal.isHittable {
                reveal.tap()
                continue
            }
            let option = app.buttons.matching(identifier: "review.option").firstMatch
            if option.exists && option.isHittable {
                option.tap()
                continue
            }
            app.swipeUp()
        }

        XCTAssertTrue(summaryDone.waitForExistence(timeout: 5), "Session summary never appeared")
        XCTAssertGreaterThan(graded, 0)
        summaryDone.tap()
        XCTAssertTrue(start.waitForExistence(timeout: 5))
    }
}
