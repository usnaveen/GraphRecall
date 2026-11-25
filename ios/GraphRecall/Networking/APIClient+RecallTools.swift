import Foundation

/// "Show me this later", LeetCode recall and structure cards. None of these call an LLM on the
/// backend, so they work on the free Gemini tier.
extension APIClient {
    private func idPath(_ raw: String) -> String {
        raw.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? raw
    }

    private var timeZoneID: String { TimeZone.current.identifier }

    // MARK: Later

    /// POST `/api/later` — the backend parses "tomorrow", "in 3 days" etc. out of `text` unless `when` is set.
    func saveForLater(text: String, url: String? = nil, when: LaterWhen? = nil, source: String = "typed") async throws -> LaterItem {
        try await post("/api/later", body: LaterCreateBody(
            text: text, url: url, when: when?.rawValue, tz: timeZoneID, source: source
        ))
    }

    /// GET `/api/later/due` — items whose time has come (the backend marks them shown).
    func dueLaterItems() async throws -> [LaterItem] {
        let response: LaterListResponse = try await get("/api/later/due")
        return response.items
    }

    /// GET `/api/later` — everything not done yet, soonest first.
    func laterItems() async throws -> [LaterItem] {
        let response: LaterListResponse = try await get("/api/later")
        return response.items
    }

    func markLaterDone(id: String) async throws {
        let _: LaterItem = try await send("/api/later/\(idPath(id))/done", method: "POST", body: Data("{}".utf8))
    }

    func snoozeLater(id: String, when: LaterWhen) async throws -> LaterItem {
        try await post("/api/later/\(idPath(id))/snooze", body: LaterSnoozeBody(when: when.rawValue, tz: timeZoneID))
    }

    // MARK: LeetCode

    func codingProblems() async throws -> [CodingProblemSummary] {
        let response: CodingProblemsResponse = try await get("/api/leetcode/problems")
        return response.problems
    }

    func codingProblem(id: String) async throws -> CodingProblemDetail {
        try await get("/api/leetcode/problems/\(idPath(id))")
    }

    /// POST `/api/leetcode/problems` — create, or update the problem with the same title.
    func saveCodingProblem(_ body: CodingProblemBody) async throws -> CodingProblemSaved {
        try await post("/api/leetcode/problems", body: body)
    }

    func logCodingAttempt(problemId: String, _ body: CodingAttemptBody) async throws -> CodingAttemptLogged {
        try await post("/api/leetcode/problems/\(idPath(problemId))/attempts", body: body)
    }

    func codingWeakSpots() async throws -> [WeakSpot] {
        let response: WeakSpotsResponse = try await get("/api/leetcode/weak-spots")
        return response.weakSpots
    }

    // MARK: Structure cards

    /// POST `/api/notes/{id}/structure-cards` — hide-the-bullets and definition cards, no LLM.
    func makeStructureCards(noteId: String, replace: Bool = false) async throws -> StructureCardsResponse {
        try await postQuery(
            "/api/notes/\(idPath(noteId))/structure-cards",
            query: [URLQueryItem(name: "replace", value: replace ? "true" : "false")]
        )
    }
}
