import Foundation

enum APIError: Error, LocalizedError {
    case invalidURL
    case http(Int, String)
    case rateLimited(retryAfter: Int?, detail: String?)
    case decoding(Error)
    case transport(Error)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid URL"
        case .http(let code, let body): return "HTTP \(code): \(body)"
        case .rateLimited(let retryAfter, let detail):
            if let detail, !detail.isEmpty { return detail }
            if let retryAfter { return "Too many requests — try again in \(retryAfter)s." }
            return "Too many requests — please slow down."
        case .decoding(let err): return "Decode failed: \(err.localizedDescription)"
        case .transport(let err): return err.localizedDescription
        }
    }

    /// Parse HTTP error responses consistently across JSON, query, and multipart requests.
    static func fromHTTPResponse(_ http: HTTPURLResponse, data: Data) -> APIError {
        let text = String(data: data, encoding: .utf8) ?? ""
        if http.statusCode == 429 {
            let retryRaw = http.value(forHTTPHeaderField: "Retry-After")?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let retrySeconds = retryRaw.flatMap(Int.init)
            var detail: String?
            if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let msg = obj["detail"] as? String {
                detail = msg
            }
            return .rateLimited(retryAfter: retrySeconds, detail: detail)
        }
        return .http(http.statusCode, text)
    }

    /// Extracts readable `detail` text from FastAPI JSON error responses.
    static func extractDetail(from body: String) -> String? {
        let trimmedBody = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedBody.isEmpty,
              let data = trimmedBody.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        if let detail = obj["detail"] as? String {
            let clean = detail.trimmingCharacters(in: .whitespacesAndNewlines)
            return clean.isEmpty ? nil : String(clean.prefix(280))
        }
        if let items = obj["detail"] as? [[String: Any]] {
            let messages = items.compactMap { ($0["msg"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
            if !messages.isEmpty {
                return String(messages.joined(separator: "; ").prefix(280))
            }
        }
        return nil
    }

    /// Short, UI-safe copy — never dump HTML / huge bodies into empty states.
    static func userFacing(_ error: Error, resource: String) -> String {
        if case let APIError.rateLimited(retryAfter, detail) = error {
            if let detail, !detail.isEmpty {
                if let retryAfter, retryAfter > 0, !detail.contains("s") {
                    return "\(detail) Try again in \(retryAfter)s."
                }
                return detail
            }
            if let retryAfter {
                return "Too many requests — try again in \(retryAfter)s."
            }
            return "Too many requests. Please try again shortly."
        }

        if case let APIError.http(code, body) = error {
            if [400, 409, 422].contains(code) || (code == 401 && resource == "account"),
               let detail = extractDetail(from: body) {
                return detail
            }
            switch code {
            case 401, 403: return "Sign in to load your \(resource)."
            case 404: return "\(resource.capitalized) API not found (404)."
            case 408, 504: return "Couldn\u{2019}t reach the \(resource) API."
            case 429: return "Too many requests. Please slow down and try again shortly."
            default: break
            }
        }

        let raw = error.localizedDescription
        let lower = raw.lowercased()
        let isHTML = lower.contains("<html") || lower.contains("<!doctype")
        let tooLong = raw.count > 180

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

    typealias TokenProvider = @Sendable (_ forceRefresh: Bool, _ failedToken: String?) async -> String?

    private let session: URLSession
    private var accessToken: String?
    private var tokenProvider: TokenProvider?

    init(session: URLSession = .shared) {
        self.session = session
    }

    func setTokenProvider(_ provider: TokenProvider?) {
        tokenProvider = provider
    }

    func setAccessToken(_ token: String?) {
        accessToken = token
        GRSharedAuth.sync(apiBaseURL: APIConfig.baseURL.absoluteString, bearerToken: token)
    }

    func getAccessToken() -> String? { accessToken }

    /// Resolves the bearer token for an upcoming request, refreshing proactively if near expiry.
    func prepareFreshToken() async -> String? {
        if let provider = tokenProvider,
           let provided = await provider(false, nil),
           !provided.isEmpty {
            return provided
        }
        return accessToken
    }

    /// Requests a single-flight session refresh after receiving HTTP 401.
    func refreshTokenAfter401(failedToken: String?) async -> String? {
        guard let provider = tokenProvider else { return nil }
        return await provider(true, failedToken)
    }

    // MARK: - Auth
    func loginWithGoogle(idToken: String) async throws -> AuthResponse {
        try await post("/auth/google", body: GoogleAuthRequest(idToken: idToken), auth: false)
    }

    func fetchAppleNonce() async throws -> AppleNonceResponse {
        try await send("/auth/apple/nonce", method: "POST", body: Data("{}".utf8), auth: false)
    }

    func loginWithApple(_ body: AppleAuthRequest) async throws -> AuthSessionResponse {
        try await post("/auth/apple", body: body, auth: false)
    }

    func exchangeGoogleSession(idToken: String) async throws -> AuthSessionResponse {
        try await post("/auth/session/google", body: GoogleSessionRequest(idToken: idToken), auth: false)
    }

    func refreshSession(refreshToken: String) async throws -> AuthSessionResponse {
        try await post("/auth/refresh", body: RefreshTokenRequest(refreshToken: refreshToken), auth: false)
    }

    func logoutSession(refreshToken: String) async throws {
        let data = try JSONEncoder().encode(RefreshTokenRequest(refreshToken: refreshToken))
        try await sendNoContent("/auth/logout", method: "POST", body: data, auth: false)
    }

    // MARK: - Feed / SM-2
    func fetchFeed() async throws -> FeedResponse {
        try await get("/api/feed")
    }

    func fetchStats() async throws -> UserStats {
        try await get("/api/feed/stats")
    }

    func submitReview(itemId: String, itemType: String, difficulty: ReviewDifficulty, conceptId: String? = nil, responseTimeMs: Int? = nil) async throws -> ReviewSubmitResult {
        var items: [URLQueryItem] = [
            URLQueryItem(name: "item_id", value: itemId),
            URLQueryItem(name: "item_type", value: itemType),
            URLQueryItem(name: "difficulty", value: difficulty.rawValue)
        ]
        // SM-2 schedules concepts, not cards: without this the server has to look the concept up.
        if let conceptId, !conceptId.isEmpty {
            items.append(URLQueryItem(name: "concept_id", value: conceptId))
        }
        if let responseTimeMs {
            items.append(URLQueryItem(name: "response_time_ms", value: String(responseTimeMs)))
        }
        return try await postQuery("/api/feed/review", query: items)
    }

    func dueCount() async throws -> DueCountResponse {
        try await get("/api/feed/due-count")
    }


    /// POST `/api/feed/{id}/like?item_type=` — toggle like; returns `{ id, is_liked }`.
    func likeFeedItem(id: String, itemType: String) async throws -> FeedLikeResponse {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        return try await postQuery(
            "/api/feed/\(encoded)/like",
            query: [URLQueryItem(name: "item_type", value: itemType)]
        )
    }

    /// POST `/api/feed/{id}/save?item_type=` — toggle save; returns `{ id, is_saved }`.
    func saveFeedItem(id: String, itemType: String) async throws -> FeedSaveResponse {
        let encoded = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
        return try await postQuery(
            "/api/feed/\(encoded)/save",
            query: [URLQueryItem(name: "item_type", value: itemType)]
        )
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
        try await post("/api/v2/ingest/youtube", body: IngestYouTubeRequest(url: url, title: title), timeout: 300)  // Gemini fallback can take minutes
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

    /// A PDF or image, read on the server (text layer, OCR for scanned pages) → `POST /api/v2/ingest/document`.
    /// Returns at once with a thread id; ingestion runs in the background like the book ZIP import.
    func ingestDocument(
        data: Data,
        filename: String,
        mimeType: String,
        title: String? = nil,
        skipReview: Bool = true
    ) async throws -> ProcessedZipIngestResponse {
        var fields: [String: String] = ["skip_review": skipReview ? "true" : "false", "resource_type": "notes"]
        if let title, !title.isEmpty { fields["title"] = title }
        return try await postMultipart(
            "/api/v2/ingest/document",
            fileFieldName: "file",
            filename: filename,
            fileData: data,
            mimeType: mimeType,
            fields: fields,
            timeout: 300
        )
    }

    /// Text of a PDF or image, read on the server with OCR where needed. Nothing is stored there.
    func extractDocumentText(data: Data, filename: String, mimeType: String) async throws -> DocumentExtractResponse {
        try await postMultipart(
            "/api/v2/ingest/document/extract",
            fileFieldName: "file",
            filename: filename,
            fileData: data,
            mimeType: mimeType,
            fields: [:],
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

    // MARK: - Profile (schedule + nested lists)

    /// GET `/api/feed/schedule` — upcoming review days with topic chips.
    func fetchSchedule(days: Int = 14) async throws -> [ScheduleDay] {
        try await get(
            "/api/feed/schedule",
            query: [URLQueryItem(name: "days", value: String(min(max(days, 1), 60)))]
        )
    }

    /// GET `/api/uploads` — user screenshots / resources.
    func fetchUploads(limit: Int = 50, offset: Int = 0) async throws -> UploadsListResponse {
        try await get(
            "/api/uploads",
            query: [
                URLQueryItem(name: "limit", value: String(min(max(limit, 1), 50))),
                URLQueryItem(name: "offset", value: String(max(offset, 0)))
            ]
        )
    }

    /// GET `/api/feed/history/quizzes` — quiz + flashcard history.
    func fetchQuizHistory() async throws -> QuizHistoryResponse {
        try await get("/api/feed/history/quizzes")
    }

    /// Concepts for Profile list — graph3d nodes mapped to `ProfileConcept`.
    func fetchProfileConcepts() async throws -> [ProfileConcept] {
        let graph = try await fetchGraph()
        return graph.nodes.map(ProfileConcept.init(from:))
    }

    // MARK: - Graph
    /// GET `/api/graph3d?limit=&offset=` — the backend defaults to 200 concepts per page.
    func fetchGraph(limit: Int = 200, offset: Int = 0) async throws -> Graph3DResponse {
        try await get(
            "/api/graph3d",
            query: [
                URLQueryItem(name: "limit", value: String(min(max(limit, 1), 5000))),
                URLQueryItem(name: "offset", value: String(max(offset, 0)))
            ]
        )
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
        sourceIds: [String]? = nil,
        userId: String = ChatIdentity.stubUserId,
        bearerToken: String? = nil,
        fromSuggestion: ChatFollowUpClick? = nil
    ) throws -> URLRequest {
        guard let url = URL(string: "/api/chat/stream", relativeTo: APIConfig.baseURL)?.absoluteURL else {
            throw APIError.invalidURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        let token = bearerToken ?? accessToken
        if let token, !token.isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        req.httpBody = try JSONEncoder().encode(
            ChatStreamRequest(
                message: message,
                conversationId: conversationId,
                userId: userId,
                sourceIds: sourceIds,
                fromSuggestion: fromSuggestion
            )
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

    /// GET `/api/chat/history` — recent conversations with preview (web Assistant list).
    func getChatHistory(limit: Int = 20) async throws -> ChatHistoryResponse {
        try await get(
            "/api/chat/history",
            query: [URLQueryItem(name: "limit", value: String(min(max(limit, 1), 50)))]
        )
    }

    /// GET `/api/chat/conversations` — simpler conversation list.
    func listConversations(limit: Int = 20) async throws -> ChatConversationsListResponse {
        try await get(
            "/api/chat/conversations",
            query: [URLQueryItem(name: "limit", value: String(min(max(limit, 1), 50)))]
        )
    }

    /// GET `/api/chat/conversations/{id}` — conversation meta + messages for thread restore.
    func getConversation(id: String) async throws -> ChatConversationDetailResponse {
        try await get("/api/chat/conversations/\(id)")
    }

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

    /// POST `/api/chat/messages/{id}/feedback` — record thumbs up/down + optional reason.
    func submitChatFeedback(
        messageId: String,
        rating: ChatFeedbackRating,
        reason: ChatFeedbackReason? = nil,
        comment: String? = nil
    ) async throws -> ChatFeedbackResponse {
        try await post(
            "/api/chat/messages/\(messageId)/feedback",
            body: ChatFeedbackRequestBody(rating: rating, reason: reason, comment: comment)
        )
    }

    /// POST `/api/chat/prefetch` — warm the query embedding on a ~600 ms typing pause.
    func prefetchChatEmbedding(text: String, conversationId: String?) async throws -> ChatPrefetchResponse {
        try await post(
            "/api/chat/prefetch",
            body: ChatPrefetchRequestBody(text: text, conversationId: conversationId)
        )
    }

    // MARK: - Core

    func get<T: Decodable>(_ path: String, query: [URLQueryItem]) async throws -> T {
        guard let base = URL(string: path, relativeTo: APIConfig.baseURL)?.absoluteURL else {
            throw APIError.invalidURL
        }
        guard var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidURL
        }
        components.queryItems = query
        guard let url = components.url else { throw APIError.invalidURL }
        return try await executeDecoded({ token in
            var req = URLRequest(url: url)
            req.httpMethod = "GET"
            req.timeoutInterval = APIConfig.defaultTimeout
            if let token, !token.isEmpty {
                req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }
            return req
        }, auth: true)
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

        return try await executeDecoded({ token in
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            req.timeoutInterval = timeout ?? APIConfig.defaultTimeout
            req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            req.httpBody = body
            if auth, let token, !token.isEmpty {
                req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }
            return req
        }, auth: auth)
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

    func get<T: Decodable>(_ path: String) async throws -> T {
        try await send(path, method: "GET", body: Data?.none)
    }

    func post<T: Decodable, B: Encodable>(
        _ path: String,
        body: B,
        auth: Bool = true,
        timeout: TimeInterval? = nil
    ) async throws -> T {
        let data = try JSONEncoder().encode(body)
        return try await send(path, method: "POST", body: data, auth: auth, timeout: timeout)
    }

    func postQuery<T: Decodable>(_ path: String, query: [URLQueryItem], auth: Bool = true) async throws -> T {
        guard let base = URL(string: path, relativeTo: APIConfig.baseURL)?.absoluteURL else {
            throw APIError.invalidURL
        }
        guard var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidURL
        }
        components.queryItems = query
        guard let url = components.url else { throw APIError.invalidURL }
        return try await executeDecoded({ token in
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            req.timeoutInterval = APIConfig.defaultTimeout
            if auth, let token, !token.isEmpty {
                req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }
            return req
        }, auth: auth)
    }

    func send<T: Decodable>(
        _ path: String,
        method: String,
        body: Data?,
        auth: Bool = true,
        timeout: TimeInterval? = nil
    ) async throws -> T {
        try await executeDecoded({ token in
            try buildJSONRequest(path: path, method: method, body: body, token: auth ? token : nil, timeout: timeout)
        }, auth: auth)
    }

    /// GET raw bytes (figures from the user's sources), with the same auth and refresh as JSON calls.
    func getData(_ path: String) async throws -> Data {
        let (data, _) = try await executeData({ token in
            try buildJSONRequest(path: path, method: "GET", body: nil, token: token, timeout: nil)
        }, auth: true)
        return data
    }

    func sendNoContent(
        _ path: String,
        method: String,
        body: Data?,
        auth: Bool = true,
        timeout: TimeInterval? = nil
    ) async throws {
        _ = try await executeData({ token in
            try buildJSONRequest(path: path, method: method, body: body, token: auth ? token : nil, timeout: timeout)
        }, auth: auth)
    }

    private func buildJSONRequest(
        path: String,
        method: String,
        body: Data?,
        token: String?,
        timeout: TimeInterval?
    ) throws -> URLRequest {
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
        if let token, !token.isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return req
    }

    private func executeDecoded<T: Decodable>(
        _ buildRequest: (String?) throws -> URLRequest,
        auth: Bool
    ) async throws -> T {
        let (data, _) = try await executeData(buildRequest, auth: auth)
        do {
            return try makeDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }

    private func executeData(
        _ buildRequest: (String?) throws -> URLRequest,
        auth: Bool
    ) async throws -> (Data, HTTPURLResponse) {
        let initialToken: String? = auth ? await prepareFreshToken() : nil
        let firstReq = try buildRequest(initialToken)
        let (firstData, firstResponse) = try await performDataTask(for: firstReq)
        guard let firstHTTP = firstResponse as? HTTPURLResponse else {
            throw APIError.http(-1, "No HTTP response")
        }

        if firstHTTP.statusCode == 401, auth,
           let refreshedToken = await refreshTokenAfter401(failedToken: initialToken),
           !refreshedToken.isEmpty {
            let retryReq = try buildRequest(refreshedToken)
            let (retryData, retryResponse) = try await performDataTask(for: retryReq)
            guard let retryHTTP = retryResponse as? HTTPURLResponse else {
                throw APIError.http(-1, "No HTTP response")
            }
            guard (200..<300).contains(retryHTTP.statusCode) else {
                throw APIError.fromHTTPResponse(retryHTTP, data: retryData)
            }
            return (retryData, retryHTTP)
        }

        guard (200..<300).contains(firstHTTP.statusCode) else {
            throw APIError.fromHTTPResponse(firstHTTP, data: firstData)
        }
        return (firstData, firstHTTP)
    }

    private func performDataTask(for request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(for: request)
        } catch {
            throw APIError.transport(error)
        }
    }
}
