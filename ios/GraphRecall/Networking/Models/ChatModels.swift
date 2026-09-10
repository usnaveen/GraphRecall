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
