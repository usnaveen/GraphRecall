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

    func dueCount() async throws -> [String: Int] {
        try await get("/api/feed/due-count")
    }

    func submitReview(itemId: String, quality: Int) async throws {
        let _: EmptyJSON = try await post(
            "/api/feed/review",
            body: ReviewSubmitRequest(itemId: itemId, quality: quality)
        )
    }

    // MARK: - Graph
    func fetchGraph() async throws -> Graph3DResponse {
        try await get("/api/graph3d")
    }

    // MARK: - Chat
    func chatStreamURLRequest(message: String, conversationId: String?) throws -> URLRequest {
        guard let url = URL(string: "/api/chat/stream", relativeTo: APIConfig.baseURL)?.absoluteURL else {
            throw APIError.invalidURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let accessToken {
            req.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        req.httpBody = try JSONEncoder().encode(ChatStreamRequest(message: message, conversationId: conversationId))
        req.timeoutInterval = APIConfig.defaultTimeout
        return req
    }

    // MARK: - Core
    private func get<T: Decodable>(_ path: String) async throws -> T {
        try await send(path, method: "GET", body: Data?.none)
    }

    private func post<T: Decodable, B: Encodable>(_ path: String, body: B, auth: Bool = true) async throws -> T {
        let data = try JSONEncoder().encode(body)
        return try await send(path, method: "POST", body: data, auth: auth)
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
                return try JSONDecoder().decode(T.self, from: data)
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
