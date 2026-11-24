import Foundation

/// REST client for the agent bridge (`/api/agent-bridge`, PR #3). The external agent itself
/// talks MCP at `/mcp/agent`; the app only uses these user-authenticated routes.
extension APIClient {
    /// Strict path-segment encoding: ids are UUIDs, but never let one inject `/` or `?`.
    fileprivate func bridgeSegment(_ raw: String) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-_")
        return raw.addingPercentEncoding(withAllowedCharacters: allowed) ?? ""
    }

    // MARK: Capability

    /// Probes whether the server has the bridge enabled. 200 → enabled; 404 → disabled
    /// (routes are not mounted unless `AGENT_BRIDGE_ENABLED=1`). Other errors are rethrown.
    /// TODO(agent-bridge-ios): replace with a real capability flag (e.g. `/health` or the
    /// auth profile returning `features.agent_bridge`) so this doesn't need a keys round-trip.
    func agentBridgeProbe() async throws -> Bool {
        do {
            let _: AgentKeysResponse = try await get("/api/agent-bridge/keys")
            return true
        } catch APIError.http(404, _) {
            return false
        }
    }

    // MARK: Feed items (approval inbox)

    /// GET `/api/agent-bridge/feed-items?status=&target_date=&limit=`
    func agentFeedItems(status: AgentFeedItemStatus? = .pending, targetDate: String? = nil, limit: Int = 50) async throws -> [AgentFeedItem] {
        var query = [URLQueryItem(name: "limit", value: String(min(max(limit, 1), 200)))]
        if let status, status != .unknown { query.append(URLQueryItem(name: "status", value: status.rawValue)) }
        if let targetDate { query.append(URLQueryItem(name: "target_date", value: targetDate)) }
        let response: AgentFeedItemsResponse = try await get("/api/agent-bridge/feed-items", query: query)
        return response.items
    }

    /// POST `/api/agent-bridge/feed-items/{id}/approve`
    func approveAgentFeedItem(id: String) async throws -> AgentFeedItem {
        let response: AgentFeedItemEnvelope = try await send(
            "/api/agent-bridge/feed-items/\(bridgeSegment(id))/approve", method: "POST", body: Data("{}".utf8)
        )
        return response.item
    }

    /// POST `/api/agent-bridge/feed-items/{id}/reject`
    func rejectAgentFeedItem(id: String) async throws -> AgentFeedItem {
        let response: AgentFeedItemEnvelope = try await send(
            "/api/agent-bridge/feed-items/\(bridgeSegment(id))/reject", method: "POST", body: Data("{}".utf8)
        )
        return response.item
    }

    // MARK: Ask my agent

    /// POST `/api/agent-bridge/requests` → 202 `{request, eta_note}`
    func askAgent(question: String, conversationId: String?, context: [String: String] = [:]) async throws -> AgentRequestCreated {
        let trimmed = String(question.trimmingCharacters(in: .whitespacesAndNewlines).prefix(4000))
        return try await post(
            "/api/agent-bridge/requests",
            body: AskAgentBody(question: trimmed, conversationId: conversationId, context: context)
        )
    }

    /// GET `/api/agent-bridge/requests/{id}`
    func agentRequest(id: String) async throws -> AgentRequest {
        let response: AgentRequestEnvelope = try await get("/api/agent-bridge/requests/\(bridgeSegment(id))")
        return response.request
    }

    /// GET `/api/agent-bridge/requests?status=a,b&limit=`
    func agentRequests(statuses: [AgentRequestStatus]? = nil, limit: Int = 20) async throws -> [AgentRequest] {
        var query = [URLQueryItem(name: "limit", value: String(min(max(limit, 1), 100)))]
        if let statuses, !statuses.isEmpty {
            query.append(URLQueryItem(name: "status", value: statuses.map(\.rawValue).joined(separator: ",")))
        }
        let response: AgentRequestsResponse = try await get("/api/agent-bridge/requests", query: query)
        return response.requests
    }

    /// POST `/api/agent-bridge/requests/{id}/cancel`
    func cancelAgentRequest(id: String) async throws -> AgentRequest {
        let response: AgentRequestEnvelope = try await send(
            "/api/agent-bridge/requests/\(bridgeSegment(id))/cancel", method: "POST", body: Data("{}".utf8)
        )
        return response.request
    }
    // TODO(agent-bridge-ios): consume GET /requests/{id}/stream (SSE) via ChatSSEClient instead
    // of polling once the server pushes status changes (LISTEN/NOTIFY); polling is fine for v1.

    // MARK: Keys

    /// GET `/api/agent-bridge/keys`
    func agentKeys() async throws -> [AgentKey] {
        let response: AgentKeysResponse = try await get("/api/agent-bridge/keys")
        return response.keys
    }

    /// POST `/api/agent-bridge/keys` → 201 with the plaintext key (shown once).
    func createAgentKey(name: String, scopes: [AgentScope], expiresInDays: Int? = 90) async throws -> CreatedAgentKey {
        try await post(
            "/api/agent-bridge/keys",
            body: CreateAgentKeyBody(name: name, scopes: scopes.map(\.rawValue), expiresInDays: expiresInDays)
        )
    }

    /// DELETE `/api/agent-bridge/keys/{id}`
    func revokeAgentKey(id: String) async throws {
        let _: RevokeAgentKeyResponse = try await send(
            "/api/agent-bridge/keys/\(bridgeSegment(id))", method: "DELETE", body: nil
        )
    }
}
