import Foundation

enum FeedItemType: String, Codable, Hashable, Sendable {
    case flashcard
    case mcq
    case fillBlank = "fill_blank"
    case infographic
    case diagram
    case screenshot
    case showcase
    case codeChallenge = "code_challenge"
}

enum ReviewDifficulty: String, Codable, CaseIterable, Identifiable, Sendable {
    case again, hard, good, easy
    var id: String { rawValue }

    var label: String {
        switch self {
        case .again: return "Again"
        case .hard: return "Hard"
        case .good: return "Good"
        case .easy: return "Easy"
        }
    }

    /// SM-2 quality mapping used locally when offline (0–5 scale).
    var sm2Quality: Int {
        switch self {
        case .again: return 1
        case .hard: return 3
        case .good: return 4
        case .easy: return 5
        }
    }
}

struct FeedResponse: Codable, Sendable {
    let items: [FeedItem]
    let totalDueToday: Int
    let completedToday: Int
    let dailyGoal: Int
    let streakDays: Int
    let domains: [String]

    enum CodingKeys: String, CodingKey {
        case items
        case totalDueToday = "total_due_today"
        case completedToday = "completed_today"
        case dailyGoal = "daily_goal"
        case streakDays = "streak_days"
        case domains
    }

    init(items: [FeedItem] = [], totalDueToday: Int = 0, completedToday: Int = 0, dailyGoal: Int = 20, streakDays: Int = 0, domains: [String] = []) {
        self.items = items
        self.totalDueToday = totalDueToday
        self.completedToday = completedToday
        self.dailyGoal = dailyGoal
        self.streakDays = streakDays
        self.domains = domains
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        items = try c.decodeIfPresent([FeedItem].self, forKey: .items) ?? []
        totalDueToday = try c.decodeIfPresent(Int.self, forKey: .totalDueToday) ?? 0
        completedToday = try c.decodeIfPresent(Int.self, forKey: .completedToday) ?? 0
        dailyGoal = try c.decodeIfPresent(Int.self, forKey: .dailyGoal) ?? 20
        streakDays = try c.decodeIfPresent(Int.self, forKey: .streakDays) ?? 0
        domains = try c.decodeIfPresent([String].self, forKey: .domains) ?? []
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(items, forKey: .items)
        try c.encode(totalDueToday, forKey: .totalDueToday)
        try c.encode(completedToday, forKey: .completedToday)
        try c.encode(dailyGoal, forKey: .dailyGoal)
        try c.encode(streakDays, forKey: .streakDays)
        try c.encode(domains, forKey: .domains)
    }
}

struct FeedItem: Codable, Sendable, Identifiable, Hashable {
    let id: String
    let itemType: FeedItemType
    let content: [String: AnyCodable]
    let conceptId: String?
    let conceptName: String?
    let domain: String?
    let priorityScore: Double?
    let dueDate: Date?

    init(
        id: String,
        itemType: FeedItemType,
        content: [String: AnyCodable] = [:],
        conceptId: String? = nil,
        conceptName: String? = nil,
        domain: String? = nil,
        priorityScore: Double? = nil,
        dueDate: Date? = nil
    ) {
        self.id = id
        self.itemType = itemType
        self.content = content
        self.conceptId = conceptId
        self.conceptName = conceptName
        self.domain = domain
        self.priorityScore = priorityScore
        self.dueDate = dueDate
    }

    enum CodingKeys: String, CodingKey {
        case id
        case itemType = "item_type"
        case content
        case conceptId = "concept_id"
        case conceptName = "concept_name"
        case domain
        case priorityScore = "priority_score"
        case dueDate = "due_date"
    }

    var title: String {
        if let name = conceptName, !name.isEmpty { return name }
        if let front = stringContent("front") { return front }
        if let q = stringContent("question") { return q }
        return itemType.rawValue.replacingOccurrences(of: "_", with: " ").capitalized
    }

    var prompt: String {
        stringContent("front")
            ?? stringContent("question")
            ?? stringContent("sentence")
            ?? stringContent("instruction")
            ?? title
    }

    var answer: String? {
        stringContent("back")
            ?? stringContent("explanation")
            ?? stringContent("solution_code")
    }

    func stringContent(_ key: String) -> String? {
        guard let v = content[key]?.value as? String, !v.isEmpty else { return nil }
        return v
    }
}

/// Type-erased JSON value for feed content blobs.
struct AnyCodable: Codable, @unchecked Sendable, Hashable {
    let value: Any

    init(_ value: Any) { self.value = value }

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { value = NSNull(); return }
        if let b = try? c.decode(Bool.self) { value = b; return }
        if let i = try? c.decode(Int.self) { value = i; return }
        if let d = try? c.decode(Double.self) { value = d; return }
        if let s = try? c.decode(String.self) { value = s; return }
        if let a = try? c.decode([AnyCodable].self) { value = a.map(\.value); return }
        if let o = try? c.decode([String: AnyCodable].self) {
            value = o.mapValues(\.value); return
        }
        value = NSNull()
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch value {
        case is NSNull: try c.encodeNil()
        case let b as Bool: try c.encode(b)
        case let i as Int: try c.encode(i)
        case let d as Double: try c.encode(d)
        case let s as String: try c.encode(s)
        case let a as [Any]: try c.encode(a.map { AnyCodable($0) })
        case let o as [String: Any]: try c.encode(o.mapValues { AnyCodable($0) })
        default: try c.encodeNil()
        }
    }

    static func == (lhs: AnyCodable, rhs: AnyCodable) -> Bool {
        String(describing: lhs.value) == String(describing: rhs.value)
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(String(describing: value))
    }
}

struct UserStats: Codable, Sendable {
    let userId: String?
    let totalConcepts: Int?
    let totalNotes: Int?
    let totalReviews: Int?
    let streakDays: Int?
    let accuracyRate: Double?
    let dueToday: Int?
    let completedToday: Int?
    let dailyGoal: Int?
    let overdue: Int?

    enum CodingKeys: String, CodingKey {
        case userId = "user_id"
        case totalConcepts = "total_concepts"
        case totalNotes = "total_notes"
        case totalReviews = "total_reviews"
        case streakDays = "streak_days"
        case accuracyRate = "accuracy_rate"
        case dueToday = "due_today"
        case completedToday = "completed_today"
        case dailyGoal = "daily_goal"
        case overdue
    }
}

struct DueCountResponse: Codable, Sendable {
    let dueToday: Int
    let overdue: Int
    let total: Int
    enum CodingKeys: String, CodingKey {
        case dueToday = "due_today"
        case overdue
        case total
    }
}

struct ReviewSubmitResult: Codable, Sendable {
    let status: String?
    let nextReview: String?
    let newIntervalDays: Int?
    let easinessFactor: Double?
    let streak: Int?
    enum CodingKeys: String, CodingKey {
        case status
        case nextReview = "next_review"
        case newIntervalDays = "new_interval_days"
        case easinessFactor = "easiness_factor"
        case streak
    }
}

struct PendingOfflineReview: Codable, Sendable, Identifiable, Hashable {
    var id: String { "\(itemId)-\(queuedAt.timeIntervalSince1970)" }
    let itemId: String
    let itemType: String
    let difficulty: ReviewDifficulty
    let queuedAt: Date
}
