import Foundation

struct ChatStreamRequest: Codable {
    let message: String
    let conversationId: String?
    /// Backend `ChatRequest` requires user_id even when JWT is present (matches web client).
    let userId: String
    let sourceIds: [String]?

    enum CodingKeys: String, CodingKey {
        case message
        case conversationId = "conversation_id"
        case userId = "user_id"
        case sourceIds = "source_ids"
    }

    init(message: String, conversationId: String? = nil, userId: String = ChatIdentity.stubUserId, sourceIds: [String]? = nil) {
        self.message = message
        self.conversationId = conversationId
        self.userId = userId
        self.sourceIds = sourceIds
    }
}

enum ChatIdentity {
    /// Matches the web client's placeholder when Google auth is not wired yet.
    static let stubUserId = "00000000-0000-0000-0000-000000000001"
}

enum ChatRole: String, Codable, Hashable {
    case user
    case assistant
    case system
}

struct ChatSuggestion: Codable, Identifiable, Hashable {
    var id: String { text }
    let text: String
}

struct ChatSuggestionsResponse: Codable {
    let suggestions: [String]
}

struct ChatSourceRef: Codable, Hashable, Identifiable {
    var id: String { stableId }
    let stableId: String
    let title: String
    let content: String?

    init(stableId: String, title: String, content: String? = nil) {
        self.stableId = stableId
        self.title = title
        self.content = content
    }

    init(from any: Any) {
        if let s = any as? String {
            self.stableId = s
            self.title = s
            self.content = nil
            return
        }
        if let dict = any as? [String: Any] {
            let title = (dict["title"] as? String)
                ?? (dict["name"] as? String)
                ?? "Source"
            let id = (dict["id"] as? String) ?? title
            self.stableId = id
            self.title = title
            self.content = dict["content"] as? String
            return
        }
        self.stableId = UUID().uuidString
        self.title = String(describing: any)
        self.content = nil
    }
}

struct ChatMessageUI: Identifiable, Hashable {
    let id: String
    var role: ChatRole
    var content: String
    var status: String?
    var sources: [ChatSourceRef]
    var relatedConcepts: [String]
    var serverId: String?
    var isStreaming: Bool

    init(
        id: String = UUID().uuidString,
        role: ChatRole,
        content: String = "",
        status: String? = nil,
        sources: [ChatSourceRef] = [],
        relatedConcepts: [String] = [],
        serverId: String? = nil,
        isStreaming: Bool = false
    ) {
        self.id = id
        self.role = role
        self.content = content
        self.status = status
        self.sources = sources
        self.relatedConcepts = relatedConcepts
        self.serverId = serverId
        self.isStreaming = isStreaming
    }
}

enum ChatSSEEvent: Equatable {
    case status(String)
    case chunk(String)
    case done(DonePayload)
    case error(String)
    case unknown

    struct DonePayload: Equatable {
        var sources: [ChatSourceRef]
        var relatedConcepts: [String]
        var messageId: String?
        var conversationId: String?
    }
}

// MARK: - Conversation list / history (L6)

struct ChatConversationSummary: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let title: String?
    let createdAt: String?
    let updatedAt: String?
    let messageCount: Int?
    let lastMessage: String?
    let summary: String?
    let isSavedToKnowledge: Bool?

    enum CodingKeys: String, CodingKey {
        case id, title, summary
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case messageCount = "message_count"
        case lastMessage = "last_message"
        case isSavedToKnowledge = "is_saved_to_knowledge"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let s = try? c.decode(String.self, forKey: .id) {
            id = s
        } else if let i = try? c.decode(Int.self, forKey: .id) {
            id = String(i)
        } else {
            id = UUID().uuidString
        }
        title = try c.decodeIfPresent(String.self, forKey: .title)
        createdAt = try Self.decodeLooseString(c, forKey: .createdAt)
        updatedAt = try Self.decodeLooseString(c, forKey: .updatedAt)
        if let n = try? c.decode(Int.self, forKey: .messageCount) {
            messageCount = n
        } else if let d = try? c.decode(Double.self, forKey: .messageCount) {
            messageCount = Int(d)
        } else {
            messageCount = try c.decodeIfPresent(Int.self, forKey: .messageCount)
        }
        lastMessage = try c.decodeIfPresent(String.self, forKey: .lastMessage)
        summary = try c.decodeIfPresent(String.self, forKey: .summary)
        isSavedToKnowledge = try c.decodeIfPresent(Bool.self, forKey: .isSavedToKnowledge)
    }

    private static func decodeLooseString(_ c: KeyedDecodingContainer<CodingKeys>, forKey key: CodingKeys) throws -> String? {
        if let s = try? c.decodeIfPresent(String.self, forKey: key) { return s }
        return nil
    }

    var displayTitle: String {
        let t = title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return t.isEmpty ? "New Chat" : t
    }

    var displaySubtitle: String {
        let count = messageCount ?? 0
        let countLabel = count == 1 ? "1 message" : "\(count) messages"
        if let updated = updatedAt, let short = Self.shortDate(updated) {
            return "\(countLabel) · \(short)"
        }
        return countLabel
    }

    private static func shortDate(_ raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let display = DateFormatter()
        display.dateStyle = .medium
        display.timeStyle = .none
        let isoFrac = ISO8601DateFormatter()
        isoFrac.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = isoFrac.date(from: trimmed) { return display.string(from: d) }
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]
        if let d = iso.date(from: trimmed) { return display.string(from: d) }
        // Python `str(datetime)` often looks like "2024-01-01 12:00:00.123456+00:00"
        let normalized = trimmed.replacingOccurrences(of: " ", with: "T")
        if let d = iso.date(from: normalized) { return display.string(from: d) }
        if trimmed.count >= 10 { return String(trimmed.prefix(10)) }
        return nil
    }
}

struct ChatHistoryResponse: Codable, Sendable {
    let conversations: [ChatConversationSummary]
    let total: Int?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversations = try c.decodeIfPresent([ChatConversationSummary].self, forKey: .conversations) ?? []
        total = try c.decodeIfPresent(Int.self, forKey: .total)
    }

    enum CodingKeys: String, CodingKey {
        case conversations, total
    }
}

struct ChatConversationsListResponse: Codable, Sendable {
    let conversations: [ChatConversationSummary]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversations = try c.decodeIfPresent([ChatConversationSummary].self, forKey: .conversations) ?? []
    }

    enum CodingKeys: String, CodingKey {
        case conversations
    }
}

struct ChatConversationMeta: Codable, Hashable, Sendable {
    let id: String
    let title: String?
    let createdAt: String?
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, title
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let s = try? c.decode(String.self, forKey: .id) {
            id = s
        } else if let i = try? c.decode(Int.self, forKey: .id) {
            id = String(i)
        } else {
            id = UUID().uuidString
        }
        title = try c.decodeIfPresent(String.self, forKey: .title)
        createdAt = try c.decodeIfPresent(String.self, forKey: .createdAt)
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
    }
}

struct ChatHistoryMessageDTO: Codable, Hashable, Sendable {
    let id: String
    let role: String
    let content: String
    let sourcesJson: [AnyCodable]?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, role, content
        case sourcesJson = "sources_json"
        case createdAt = "created_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let s = try? c.decode(String.self, forKey: .id) {
            id = s
        } else if let i = try? c.decode(Int.self, forKey: .id) {
            id = String(i)
        } else {
            id = UUID().uuidString
        }
        role = try c.decodeIfPresent(String.self, forKey: .role) ?? "assistant"
        content = try c.decodeIfPresent(String.self, forKey: .content) ?? ""
        createdAt = try c.decodeIfPresent(String.self, forKey: .createdAt)

        if let arr = try? c.decode([AnyCodable].self, forKey: .sourcesJson) {
            sourcesJson = arr
        } else if let raw = try? c.decode(String.self, forKey: .sourcesJson),
                  let data = raw.data(using: .utf8),
                  let parsed = try? JSONDecoder().decode([AnyCodable].self, from: data) {
            sourcesJson = parsed
        } else {
            sourcesJson = nil
        }
    }

    func asUIMessage() -> ChatMessageUI {
        let mappedRole = ChatRole(rawValue: role) ?? .assistant
        let sources: [ChatSourceRef] = (sourcesJson ?? []).map { ChatSourceRef(from: $0.value) }
        return ChatMessageUI(
            id: id,
            role: mappedRole,
            content: content,
            sources: sources,
            serverId: mappedRole == .assistant ? id : nil,
            isStreaming: false
        )
    }
}

struct ChatConversationDetailResponse: Codable, Sendable {
    let conversation: ChatConversationMeta?
    let messages: [ChatHistoryMessageDTO]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversation = try c.decodeIfPresent(ChatConversationMeta.self, forKey: .conversation)
        messages = try c.decodeIfPresent([ChatHistoryMessageDTO].self, forKey: .messages) ?? []
    }

    enum CodingKeys: String, CodingKey {
        case conversation, messages
    }
}

// MARK: - Create card / save message (M8)

enum CreateCardOutputType: String, Codable, Sendable {
    case quiz
    case conceptCard = "concept_card"

    var feedLabel: String {
        switch self {
        case .quiz: return "Quiz"
        case .conceptCard: return "Concept card"
        }
    }
}

struct CreateCardRequestBody: Encodable, Sendable {
    let outputType: String
    let topic: String?

    enum CodingKeys: String, CodingKey {
        case outputType = "output_type"
        case topic
    }

    init(outputType: CreateCardOutputType, topic: String? = nil) {
        self.outputType = outputType.rawValue
        self.topic = topic
    }
}

struct SaveMessageRequestBody: Encodable, Sendable {
    let topic: String?
}

struct CreateCardOptionDTO: Decodable, Sendable, Hashable {
    let id: String?
    let text: String?
    let isCorrect: Bool?

    enum CodingKeys: String, CodingKey {
        case id, text
        case isCorrect = "is_correct"
    }
}

struct CreateCardResponse: Decodable, Sendable {
    let id: String
    let type: String
    let frontContent: String?
    let backContent: String?
    let questionText: String?
    let questionType: String?
    let options: [CreateCardOptionDTO]?
    let correctAnswer: String?
    let explanation: String?
    let topic: String?
    let source: String?

    enum CodingKeys: String, CodingKey {
        case id, type, options, topic, source
        case frontContent = "front_content"
        case backContent = "back_content"
        case questionText = "question_text"
        case questionType = "question_type"
        case correctAnswer = "correct_answer"
        case explanation
    }

    /// Map API create-card payload → FeedItem for OfflineReviewStore / Today.
    func asFeedItem() -> FeedItem {
        let trimmed = topic?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let topicName = trimmed.isEmpty ? "Chat Card" : trimmed
        let parsed = FeedItemType.parse(type)
        switch parsed {
        case .mcq:
            var content: [String: AnyCodable] = [
                "question": AnyCodable(questionText ?? topicName)
            ]
            if let options {
                let mapped: [[String: Any]] = options.enumerated().map { idx, o in
                    [
                        "id": o.id ?? "opt-\(idx)",
                        "text": o.text ?? "Option \(idx + 1)",
                        "is_correct": o.isCorrect ?? false
                    ]
                }
                content["options"] = AnyCodable(mapped)
            }
            if let correctAnswer { content["correct_answer"] = AnyCodable(correctAnswer) }
            if let explanation { content["explanation"] = AnyCodable(explanation) }
            return FeedItem(
                id: id,
                itemType: .mcq,
                content: content,
                conceptId: nil,
                conceptName: topicName,
                domain: "assistant",
                priorityScore: 1.1,
                dueDate: Date()
            )
        default:
            var content: [String: AnyCodable] = [:]
            content["front"] = AnyCodable(frontContent ?? topicName)
            if let backContent { content["back"] = AnyCodable(backContent) }
            return FeedItem(
                id: id,
                itemType: .flashcard,
                content: content,
                conceptId: nil,
                conceptName: topicName,
                domain: "assistant",
                priorityScore: 1.1,
                dueDate: Date()
            )
        }
    }
}

struct SaveMessageResponse: Decodable, Sendable {
    let savedId: String?
    let messageId: String?
    let topic: String?
    let status: String?

    enum CodingKeys: String, CodingKey {
        case topic, status
        case savedId = "saved_id"
        case messageId = "message_id"
    }
}

enum ChatLocalFeedFactory {
    /// Offline / stub path when `serverId` is missing — DemoFeedSeed-style local card.
    static func makeLocalCard(
        from message: ChatMessageUI,
        outputType: CreateCardOutputType
    ) -> FeedItem {
        let topic = message.relatedConcepts.first
            ?? String(message.content.prefix(48)).trimmingCharacters(in: .whitespacesAndNewlines)
        let topicName = topic.isEmpty ? "Chat Card" : topic
        let snippet = String(message.content.prefix(400))
        let id = "demo-chat-\(outputType.rawValue)-\(UUID().uuidString.prefix(8))"

        switch outputType {
        case .quiz:
            let options = [
                "Recall the key idea from this answer",
                "A related but incorrect detail",
                "An unrelated concept",
                "None of the above"
            ]
            return FeedItem(
                id: id,
                itemType: .mcq,
                content: [
                    "question": AnyCodable("Quiz from Assistant: what is the core idea behind \"\(topicName)\"?"),
                    "options": AnyCodable(options),
                    "correct_answer": AnyCodable(options[0]),
                    "explanation": AnyCodable(snippet)
                ],
                conceptId: nil,
                conceptName: topicName,
                domain: "Demo",
                priorityScore: 1.0,
                dueDate: Date()
            )
        case .conceptCard:
            return FeedItem(
                id: id,
                itemType: .flashcard,
                content: [
                    "front": AnyCodable(topicName),
                    "back": AnyCodable(snippet.isEmpty ? "Saved from Assistant (offline)." : snippet)
                ],
                conceptId: nil,
                conceptName: topicName,
                domain: "Demo",
                priorityScore: 1.0,
                dueDate: Date()
            )
        }
    }
}
