import Foundation

/// Endpoints used by the revamped screens (search, concept focus, link suggestions,
/// merge, human-in-the-loop import review, saved items, knowledge summary, purge).
extension APIClient {
    private func pathComponent(_ raw: String) -> String {
        raw.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? raw
    }

    // MARK: Graph

    /// GET `/api/graph3d/search?query=`
    func searchConcepts(_ query: String, limit: Int = 12) async throws -> [GraphSearchResult] {
        let response: GraphSearchResponse = try await get(
            "/api/graph3d/search",
            query: [
                URLQueryItem(name: "query", value: query),
                URLQueryItem(name: "limit", value: String(min(max(limit, 1), 20)))
            ]
        )
        return response.results
    }

    /// GET `/api/graph3d/focus/{id}` — center concept, connections, mastery.
    func focusConcept(id: String, depth: Int = 2) async throws -> ConceptFocusResponse {
        try await get(
            "/api/graph3d/focus/\(pathComponent(id))",
            query: [URLQueryItem(name: "depth", value: String(min(max(depth, 1), 4)))]
        )
    }

    /// POST `/api/nodes/{id}/suggest-links` — LLM link suggestions for a concept.
    func suggestLinks(nodeId: String) async throws -> [LinkSuggestion] {
        let response: LinkSuggestionsResponse = try await send(
            "/api/nodes/\(pathComponent(nodeId))/suggest-links",
            method: "POST",
            body: Data("{}".utf8),
            timeout: 120
        )
        return response.links
    }

    /// POST `/api/nodes/{id}/link` — apply approved suggestions.
    func applyLinks(nodeId: String, links: [LinkSuggestion]) async throws {
        let _: EmptyJSON = try await post("/api/nodes/\(pathComponent(nodeId))/link", body: ApplyLinksBody(links: links))
    }

    /// POST `/api/concepts/merge` — fold `sourceIds` into `targetId`.
    func mergeConcepts(sourceIds: [String], into targetId: String) async throws {
        let _: EmptyJSON = try await post(
            "/api/concepts/merge",
            body: MergeConceptsBody(sourceIds: sourceIds, targetId: targetId),
            timeout: 120
        )
    }

    // MARK: Import review (HITL)

    /// POST `/api/review/ingest` with `skip_review: false` — returns a session to approve.
    func ingestWithReview(content: String, sourceURL: String? = nil) async throws -> ReviewIngestResponse {
        try await post(
            "/api/review/ingest",
            body: ReviewIngestBody(content: content, sourceURL: sourceURL, skipReview: false),
            timeout: 300
        )
    }

    func pendingReviewSessions() async throws -> [PendingReviewSession] {
        let response: PendingReviewSessionsResponse = try await get("/api/review/sessions")
        return response.sessions
    }

    func reviewSession(id: String) async throws -> ConceptReviewSession {
        try await get("/api/review/sessions/\(pathComponent(id))")
    }

    func approveReviewSession(id: String, approved: [ConceptReviewItem], removedIds: [String]) async throws {
        let _: EmptyJSON = try await post(
            "/api/review/sessions/\(pathComponent(id))/approve",
            body: ConceptReviewApprovalBody(
                sessionId: id,
                approvedConcepts: approved,
                removedConceptIds: removedIds,
                addedConcepts: []
            ),
            timeout: 300
        )
    }

    func cancelReviewSession(id: String) async throws {
        let _: EmptyJSON = try await send(
            "/api/review/sessions/\(pathComponent(id))/cancel",
            method: "POST",
            body: Data("{}".utf8)
        )
    }

    // MARK: Profile

    func fetchSavedItems() async throws -> SavedItemsResponse {
        try await get("/api/feed/saved")
    }

    func fetchKnowledgeSummary() async throws -> KnowledgeSummaryResponse {
        try await get("/api/knowledge/summary")
    }

    /// DELETE `/api/users/me/purge` — 204 with an empty body.
    func purgeMyData() async throws {
        do {
            let _: EmptyJSON = try await send("/api/users/me/purge", method: "DELETE", body: nil, timeout: 120)
        } catch APIError.decoding(_) {
            // 204 No Content has no JSON body — the purge still succeeded.
        }
    }
}
