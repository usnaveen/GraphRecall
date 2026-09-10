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
