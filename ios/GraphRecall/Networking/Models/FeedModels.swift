import Foundation

struct FeedResponse: Codable {
    let items: [FeedItem]
    let dueCount: Int?
    enum CodingKeys: String, CodingKey {
        case items
        case dueCount = "due_count"
    }
}

struct FeedItem: Codable, Identifiable {
    let id: String
    let type: String?
    let title: String?
    let conceptName: String?
    enum CodingKeys: String, CodingKey {
        case id, type, title
        case conceptName = "concept_name"
    }
}

struct UserStats: Codable {
    let reviewsToday: Int?
    let dueCount: Int?
    let streak: Int?
    enum CodingKeys: String, CodingKey {
        case reviewsToday = "reviews_today"
        case dueCount = "due_count"
        case streak
    }
}

struct ReviewSubmitRequest: Codable {
    let itemId: String
    let quality: Int
    enum CodingKeys: String, CodingKey {
        case itemId = "item_id"
        case quality
    }
}
