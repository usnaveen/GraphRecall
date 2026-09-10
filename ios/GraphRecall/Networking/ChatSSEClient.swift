import Foundation

/// URLSession-backed Server-Sent Events client for `POST /api/chat/stream`.
actor ChatSSEClient {
    static let shared = ChatSSEClient()

    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    /// Streams SSE events. Throws on transport/HTTP failure before the body starts.
    func stream(
        message: String,
        conversationId: String?,
        accessToken: String?,
        userId: String = ChatIdentity.stubUserId
    ) -> AsyncThrowingStream<ChatSSEEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let request = try await APIClient.shared.chatStreamURLRequest(
                        message: message,
                        conversationId: conversationId,
                        userId: userId
                    )
                    let (bytes, response) = try await session.bytes(for: request)
                    if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                        var body = ""
                        for try await line in bytes.lines {
                            body += line
                            if body.count > 2000 { break }
                        }
                        throw APIError.http(http.statusCode, body)
                    }

                    var buffer = ""
                    for try await line in bytes.lines {
                        if Task.isCancelled { break }
                        if line.hasPrefix("data:") {
                            let payload = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
                            if payload.isEmpty || payload == "[DONE]" { continue }
                            let event = Self.parseEvent(payload)
                            continuation.yield(event)
                            if case .done = event { break }
                            if case .error = event { break }
                        } else if line.isEmpty {
                            buffer = ""
                        } else {
                            buffer += line
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// Local stub stream used when auth/base URL is missing — keeps UI demoable.
    func stubStream(message: String) -> AsyncThrowingStream<ChatSSEEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                let reply = """
                *(Stub mode — set a Bearer token via APIClient and point GRAPHRECALL_API_BASE at FastAPI.)*

                You asked: **\(message)**

                GraphRecall will stream GraphRAG tokens here once `/api/chat/stream` is reachable.
                """
                continuation.yield(.status("Connecting (stub)…"))
                try? await Task.sleep(nanoseconds: 250_000_000)
                continuation.yield(.status("Analyzing intent…"))
                try? await Task.sleep(nanoseconds: 200_000_000)

                var assembled = ""
                for word in reply.split(separator: " ", omittingEmptySubsequences: false) {
                    if Task.isCancelled { break }
                    let piece = assembled.isEmpty ? String(word) : " " + word
                    assembled += piece
                    continuation.yield(.chunk(piece))
                    try? await Task.sleep(nanoseconds: 18_000_000)
                }
                continuation.yield(.done(.init(
                    sources: [ChatSourceRef(stableId: "stub", title: "Local stub")],
                    relatedConcepts: ["GraphRAG", "SSE"],
                    messageId: nil,
                    conversationId: nil
                )))
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    nonisolated static func parseEvent(_ payload: String) -> ChatSSEEvent {
        guard let data = payload.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = obj["type"] as? String
        else {
            return .unknown
        }

        switch type {
        case "status":
            return .status((obj["content"] as? String) ?? "Working…")
        case "chunk":
            return .chunk((obj["content"] as? String) ?? "")
        case "error":
            return .error((obj["error"] as? String) ?? "Stream error")
        case "done":
            let sourcesRaw = obj["sources"] as? [Any] ?? []
            let conceptsRaw = obj["related_concepts"] as? [Any] ?? []
            let sources = sourcesRaw.map { ChatSourceRef(from: $0) }
            let concepts: [String] = conceptsRaw.compactMap { item in
                if let s = item as? String { return s }
                if let d = item as? [String: Any] {
                    return (d["name"] as? String) ?? (d["title"] as? String)
                }
                return nil
            }
            let messageId: String? = {
                if let s = obj["message_id"] as? String { return s }
                if let n = obj["message_id"] as? NSNumber { return n.stringValue }
                return nil
            }()
            let conversationId: String? = {
                if let s = obj["conversation_id"] as? String { return s }
                if let n = obj["conversation_id"] as? NSNumber { return n.stringValue }
                return nil
            }()
            return .done(.init(
                sources: sources,
                relatedConcepts: concepts,
                messageId: messageId,
                conversationId: conversationId
            ))
        default:
            return .unknown
        }
    }
}
