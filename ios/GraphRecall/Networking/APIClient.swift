import Foundation

enum APIError: Error, LocalizedError {
    case invalidURL
    case http(Int, String)
    case decoding(Error)
    case transport(Error)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid URL"
        case .http(let code, let body): return "HTTP \(code): \(body)"
        case .decoding(let err): return "Decode failed: \(err.localizedDescription)"
        case .transport(let err): return err.localizedDescription
        }
    }
}

struct EmptyJSON: Decodable {}

actor APIClient {
    static let shared = APIClient()

    private let session: URLSession
    private var accessToken: String?

    init(session: URLSession = .shared) {
        self.session = session
    }

    func setAccessToken(_ token: String?) {
        accessToken = token
    }

    func getAccessToken() -> String? { accessToken }

    // MARK: - Auth
    func loginWithGoogle(idToken: String) async throws -> AuthResponse {
        try await post("/auth/google", body: GoogleAuthRequest(idToken: idToken), auth: false)
    }

    // MARK: - Feed / SM-2
    func fetchFeed() async throws -> FeedResponse {
        try await get("/api/feed")
    }

    func fetchStats() async throws -> UserStats {
        try await get("/api/feed/stats")
    }

    func submitReview(itemId: String, itemType: String, difficulty: ReviewDifficulty, responseTimeMs: Int? = nil) async throws -> ReviewSubmitResult {
        var items: [URLQueryItem] = [
            URLQueryItem(name: "item_id", value: itemId),
            URLQueryItem(name: "item_type", value: itemType),
            URLQueryItem(name: "difficulty", value: difficulty.rawValue)
        ]
        if let responseTimeMs {
            items.append(URLQueryItem(name: "response_time_ms", value: String(responseTimeMs)))
        }
        return try await postQuery("/api/feed/review", query: items)
    }

    func dueCount() async throws -> DueCountResponse {
        try await get("/api/feed/due-count")
    }

    // MARK: - Graph
    func fetchGraph() async throws -> Graph3DResponse {
        try await get("/api/graph3d")
    }

    // MARK: - Chat
    func chatStreamURLRequest(
        message: String,
        conversationId: String?,
        userId: String = ChatIdentity.stubUserId
    ) throws -> URLRequest {
        guard let url = URL(string: "/api/chat/stream", relativeTo: APIConfig.baseURL)?.absoluteURL else {
            throw APIError.invalidURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        if let accessToken {
            req.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        req.httpBody = try JSONEncoder().encode(
            ChatStreamRequest(message: message, conversationId: conversationId, userId: userId)
        )
        // SSE can run longer than a normal REST call.
        req.timeoutInterval = max(APIConfig.defaultTimeout, 300)
        return req
    }

    func fetchChatSuggestions() async throws -> [String] {
        let response: ChatSuggestionsResponse = try await get("/api/chat/suggestions")
        return response.suggestions
    }

    /// True when a Bearer token has been set (Google auth wiring comes later).
    var hasAuthToken: Bool { accessToken != nil && !(accessToken?.isEmpty ?? true) }

    // MARK: - Core

    private func makeDecoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .custom { decoder in
            let c = try decoder.singleValueContainer()
            let s = try c.decode(String.self)
            if let date = ISO8601DateFormatter().date(from: s) { return date }
            let f = ISO8601DateFormatter()
            f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = f.date(from: s) { return date }
            throw DecodingError.dataCorruptedError(in: c, debugDescription: "Bad date: \(s)")
        }
        return d
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        try await send(path, method: "GET", body: Data?.none)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B, auth: Bool = true) async throws -> T {
        let data = try JSONEncoder().encode(body)
        return try await send(path, method: "POST", body: data, auth: auth)
    }


    private func postQuery<T: Decodable>(_ path: String, query: [URLQueryItem], auth: Bool = true) async throws -> T {
        guard let base = URL(string: path, relativeTo: APIConfig.baseURL)?.absoluteURL else {
            throw APIError.invalidURL
        }
        guard var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidURL
        }
        components.queryItems = query
        guard let url = components.url else { throw APIError.invalidURL }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = APIConfig.defaultTimeout
        if auth, let accessToken {
            req.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        do {
            let (data, response) = try await session.data(for: req)
            guard let http = response as? HTTPURLResponse else {
                throw APIError.http(-1, "No HTTP response")
            }
            guard (200..<300).contains(http.statusCode) else {
                let body = String(data: data, encoding: .utf8) ?? ""
                throw APIError.http(http.statusCode, body)
            }
            do {
                return try makeDecoder().decode(T.self, from: data)
            } catch {
                throw APIError.decoding(error)
            }
        } catch let err as APIError {
            throw err
        } catch {
            throw APIError.transport(error)
        }
    }

    private func send<T: Decodable>(_ path: String, method: String, body: Data?, auth: Bool = true) async throws -> T {
        guard let url = URL(string: path, relativeTo: APIConfig.baseURL)?.absoluteURL else {
            throw APIError.invalidURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = APIConfig.defaultTimeout
        if let body {
            req.httpBody = body
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if auth, let accessToken {
            req.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        do {
            let (data, response) = try await session.data(for: req)
            guard let http = response as? HTTPURLResponse else {
                throw APIError.http(-1, "No HTTP response")
            }
            guard (200..<300).contains(http.statusCode) else {
                let text = String(data: data, encoding: .utf8) ?? ""
                throw APIError.http(http.statusCode, text)
            }
            do {
                return try makeDecoder().decode(T.self, from: data)
            } catch {
                throw APIError.decoding(error)
            }
        } catch let err as APIError {
            throw err
        } catch {
            throw APIError.transport(error)
        }
    }
}
