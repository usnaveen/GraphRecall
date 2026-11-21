import Foundation

/// Endpoints for Always-On Agent v2 proactive feed insights (`/api/v2/agent`).
extension APIClient {
    private func agentPathComponent(_ raw: String) -> String {
        raw.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? raw
    }

    /// GET `/api/v2/agent/feed-cards?limit=`
    func fetchAgentFeedCards(limit: Int = 20) async throws -> [AgentFeedCard] {
        let clamped = min(max(limit, 1), 100)
        let response: AgentFeedCardListResponse = try await get("/api/v2/agent/feed-cards?limit=\(clamped)")
        return response.cards
    }

    /// POST `/api/v2/agent/insights/{id}/dismiss`
    func dismissAgentInsight(id: String) async throws -> AgentInsightActionResponse {
        try await send(
            "/api/v2/agent/insights/\(agentPathComponent(id))/dismiss",
            method: "POST",
            body: Data("{}".utf8)
        )
    }

    /// POST `/api/v2/agent/insights/{id}/act`
    func actOnAgentInsight(id: String) async throws -> AgentInsightActionResponse {
        try await send(
            "/api/v2/agent/insights/\(agentPathComponent(id))/act",
            method: "POST",
            body: Data("{}".utf8)
        )
    }
}
