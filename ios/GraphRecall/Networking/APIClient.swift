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

    /// Short, UI-safe copy — never dump HTML / huge bodies into empty states.
    static func userFacing(_ error: Error, resource: String) -> String {
        let raw = error.localizedDescription
        let lower = raw.lowercased()
        let isHTML = lower.contains("<html") || lower.contains("<!doctype")
        let tooLong = raw.count > 180

        if case let APIError.http(code, _) = error {
            switch code {
            case 401, 403: return "Sign in to load your \(resource)."
            case 404: return "\(resource.capitalized) API not found (404)."
            case 408, 504: return "Couldn\u{2019}t reach the \(resource) API."
            default: break
            }
        }

        if isHTML || tooLong {
            if lower.contains("404") { return "\(resource.capitalized) API not found (404)." }
            if lower.contains("401") || lower.contains("403") { return "Sign in to load your \(resource)." }
            if lower.contains("timed out") || lower.contains("offline") || lower.contains("notconnected") {
                return "Couldn\u{2019}t reach the \(resource) API."
            }
            return "Couldn\u{2019}t reach the \(resource) API."
        }
        return raw
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

    // MARK: - Concept Dump
    func dumpConcepts(_ concepts: [String]) async throws -> ConceptDumpResponse {
        try await post("/api/concepts/dump", body: ConceptDumpRequest(concepts: concepts))
    }

    // MARK: - V2 Ingest
    /// Text / notes ingestion. Uses `skip_review: true` on iOS v1 (no HITL UI yet).
    func ingestText(content: String, title: String? = nil, resourceType: String? = "notes") async throws -> IngestResponse {
        try await post(
            "/api/v2/ingest",
            body: IngestTextRequest(
                content: content,
                title: title,
                skipReview: true,
                resourceType: resourceType
            ),
            timeout: 300
        )
    }

    func ingestURL(_ url: String) async throws -> IngestResponse {
        try await post("/api/v2/ingest/url", body: IngestURLRequest(url: url), timeout: 300)
    }

    func ingestYouTube(url: String, title: String? = nil) async throws -> IngestYouTubeResponse {
        try await post("/api/v2/ingest/youtube", body: IngestYouTubeRequest(url: url, title: title), timeout: 60)
    }

    func ingestChatTranscript(content: String, title: String? = nil) async throws -> IngestResponse {
        try await post(
            "/api/v2/ingest/chat-transcript",
            body: IngestChatTranscriptRequest(content: content, title: title),
            timeout: 300
        )
    }

    func ingestStatus(threadId: String) async throws -> IngestStatusResponse {
        try await get("/api/v2/ingest/\(threadId)/status")
    }

    /// Multipart processed-book ZIP → `POST /api/v2/ingest/processed-zip`
    /// Form fields: `file`, `skip_review`, optional `title`, optional `resource_type` (default book).
    func ingestProcessedZip(
        fileURL: URL,
        title: String? = nil,
        resourceType: String? = "book",
        skipReview: Bool = true
    ) async throws -> ProcessedZipIngestResponse {
        let filename = fileURL.lastPathComponent
        let data = try Data(contentsOf: fileURL)
        var fields: [String: String] = [
            "skip_review": skipReview ? "true" : "false"
        ]
        if let title, !title.isEmpty { fields["title"] = title }
        if let resourceType, !resourceType.isEmpty { fields["resource_type"] = resourceType }
        return try await postMultipart(
            "/api/v2/ingest/processed-zip",
            fileFieldName: "file",
            filename: filename,
            fileData: data,
            mimeType: "application/zip",
            fields: fields,
            timeout: 300
        )
    }

    // MARK: - Notes / Library

    func fetchNotes(resourceType: String? = nil, limit: Int = 50, offset: Int = 0) async throws -> NotesListResponse {
        var items: [URLQueryItem] = [
            URLQueryItem(name: "limit", value: String(limit)),
            URLQueryItem(name: "offset", value: String(offset))
        ]
        if let resourceType, !resourceType.isEmpty {
            items.append(URLQueryItem(name: "resource_type", value: resourceType))
        }
        return try await get("/api/notes", query: items)
    }

    func fetchLibraryBooks(limit: Int = 100, offset: Int = 0) async throws -> NotesListResponse {
        try await fetchNotes(resourceType: "book", limit: limit, offset: offset)
    }

    // MARK: - Graph
    func fetchGraph() async throws -> Graph3DResponse {
        try await get("/api/graph3d")
    }

    /// Louvain recompute — returns status/count; caller should reload `/api/graph3d`.
    func recomputeCommunities() async throws -> CommunitiesRecomputeResponse {
        try await send(
            "/api/graph3d/communities/recompute",
            method: "POST",
            body: Data("{}".utf8)
        )
    }

    /// GET `/api/concepts/{id}/notes` — NotePanel source chunks.
    func fetchConceptNotes(conceptId: String) async throws -> ConceptNotesResponse {
        let encoded = conceptId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? conceptId
        return try await get("/api/concepts/\(encoded)/notes")
    }

    /// GET `/api/feed/resources/{name}` — notes / links / saved responses for a concept title.
    func fetchConceptResources(conceptName: String) async throws -> ConceptResourcesResponse {
        let encoded = conceptName.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? conceptName
        return try await get("/api/feed/resources/\(encoded)")
    }

    /// POST `/api/feed/quiz/topic/{name}` — generate quiz cards into Feed (returns count).
    func generateTopicQuiz(
        topic: String,
        targetPoolSize: Int = 8,
        forceResearch: Bool = false,
        allowWebSearch: Bool = false
    ) async throws -> TopicQuizGenerateResponse {
        let encoded = topic.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? topic
        return try await post(
            "/api/feed/quiz/topic/\(encoded)",
            body: TopicQuizRequestBody(
                forceResearch: forceResearch,
                targetPoolSize: targetPoolSize,
                allowWebSearch: allowWebSearch
            ),
            timeout: 180
        )
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

    /// POST `/api/chat/messages/{id}/create-card` — quiz | concept_card.
    func createCardFromMessage(
        messageId: String,
        outputType: CreateCardOutputType,
        topic: String? = nil
    ) async throws -> CreateCardResponse {
        try await post(
            "/api/chat/messages/\(messageId)/create-card",
            body: CreateCardRequestBody(outputType: outputType, topic: topic)
        )
    }

    /// POST `/api/chat/messages/{id}/save` — mark for future quiz generation.
    func saveChatMessage(messageId: String, topic: String? = nil) async throws -> SaveMessageResponse {
        try await post(
            "/api/chat/messages/\(messageId)/save",
            body: SaveMessageRequestBody(topic: topic)
        )
    }

    // MARK: - Core

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem]) async throws -> T {
        guard let base = URL(string: path, relativeTo: APIConfig.baseURL)?.absoluteURL else {
            throw APIError.invalidURL
        }
        guard var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidURL
        }
        components.queryItems = query
        guard let url = components.url else { throw APIError.invalidURL }
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        req.timeoutInterval = APIConfig.defaultTimeout
        if let accessToken {
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

    private func postMultipart<T: Decodable>(
        _ path: String,
        fileFieldName: String,
        filename: String,
        fileData: Data,
        mimeType: String,
        fields: [String: String],
        auth: Bool = true,
        timeout: TimeInterval? = nil
    ) async throws -> T {
        guard let url = URL(string: path, relativeTo: APIConfig.baseURL)?.absoluteURL else {
            throw APIError.invalidURL
        }
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()
        for (key, value) in fields {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"\(key)\"\r\n\r\n".data(using: .utf8)!)
            body.append("\(value)\r\n".data(using: .utf8)!)
        }
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append(
            "Content-Disposition: form-data; name=\"\(fileFieldName)\"; filename=\"\(filename)\"\r\n"
                .data(using: .utf8)!
        )
        body.append("Content-Type: \(mimeType)\r\n\r\n".data(using: .utf8)!)
        body.append(fileData)
        body.append("\r\n".data(using: .utf8)!)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = timeout ?? APIConfig.defaultTimeout
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
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

    private func post<T: Decodable, B: Encodable>(
        _ path: String,
        body: B,
        auth: Bool = true,
        timeout: TimeInterval? = nil
    ) async throws -> T {
        let data = try JSONEncoder().encode(body)
        return try await send(path, method: "POST", body: data, auth: auth, timeout: timeout)
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

    private func send<T: Decodable>(
        _ path: String,
        method: String,
        body: Data?,
        auth: Bool = true,
        timeout: TimeInterval? = nil
    ) async throws -> T {
        guard let url = URL(string: path, relativeTo: APIConfig.baseURL)?.absoluteURL else {
            throw APIError.invalidURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = timeout ?? APIConfig.defaultTimeout
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
