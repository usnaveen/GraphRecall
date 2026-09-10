import Foundation

struct ChatStreamRequest: Codable {
    let message: String
    let conversationId: String?
    enum CodingKeys: String, CodingKey {
        case message
        case conversationId = "conversation_id"
    }
}

struct ChatSuggestion: Codable, Identifiable {
    var id: String { text }
    let text: String
}
