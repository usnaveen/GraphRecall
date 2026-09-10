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

    /// Accept backend wire values *and* web CardType aliases (`quiz`, `fillblank`, etc.).
    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = FeedItemType.parse(raw)
    }

    static func parse(_ raw: String) -> FeedItemType {
        switch raw.lowercased() {
        case "flashcard", "term_card": return .flashcard
        case "mcq", "quiz": return .mcq
        case "fill_blank", "fillblank": return .fillBlank
        case "infographic": return .infographic
        case "diagram": return .diagram
        case "screenshot": return .screenshot
        case "showcase", "concept_showcase": return .showcase
        case "code_challenge": return .codeChallenge
        default: return .flashcard
        }
    }

    var displayLabel: String {
        switch self {
        case .flashcard: return "Term Card"
        case .mcq: return "Quiz"
        case .fillBlank: return "Fill in the Blank"
        case .infographic: return "Infographic"
        case .diagram: return "Diagram"
        case .screenshot: return "Screenshot"
        case .showcase: return "Concept Showcase"
        case .codeChallenge: return "Code Challenge"
        }
    }

    var accentColorName: String {
        switch self {
        case .flashcard, .showcase: return "accent"
        case .mcq: return "accent"
        case .fillBlank, .codeChallenge: return "cyan"
        case .diagram: return "purple"
        case .screenshot, .infographic: return "coral"
        }
    }
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

struct FeedMCQOption: Hashable, Sendable, Identifiable {
    let id: String
    let text: String
    let isCorrect: Bool
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

    var isDemo: Bool {
        id.hasPrefix("demo-") || domain?.caseInsensitiveCompare("Demo") == .orderedSame
    }

    var title: String {
        if let name = conceptName, !name.isEmpty { return name }
        if let front = stringContent("front") { return front }
        if let q = stringContent("question") { return q }
        if let t = stringContent("title") { return t }
        return itemType.displayLabel
    }

    var prompt: String {
        stringContent("front")
            ?? stringContent("question")
            ?? stringContent("sentence")
            ?? stringContent("instruction")
            ?? stringContent("description")
            ?? stringContent("definition")
            ?? title
    }

    var answer: String? {
        stringContent("back")
            ?? stringContent("explanation")
            ?? stringContent("solution_code")
            ?? stringContent("solutionCode")
            ?? firstAnswerFromList()
    }

    func stringContent(_ key: String) -> String? {
        guard let v = content[key]?.value as? String, !v.isEmpty else { return nil }
        return v
    }

    func stringArrayContent(_ key: String) -> [String] {
        if let arr = content[key]?.value as? [String] { return arr }
        if let arr = content[key]?.value as? [Any] {
            return arr.compactMap { $0 as? String }
        }
        return []
    }

    func firstAnswerFromList() -> String? {
        let answers = stringArrayContent("answers")
        if let first = answers.first { return first }
        return stringContent("answer")
    }

    var mcqOptions: [FeedMCQOption] {
        guard let raw = content["options"]?.value else { return [] }

        if let strings = raw as? [String] {
            let correct = stringContent("correct_answer")
            return strings.enumerated().map { idx, text in
                FeedMCQOption(
                    id: "opt-\(idx)",
                    text: text,
                    isCorrect: correct.map { $0 == text } ?? false
                )
            }
        }

        if let dicts = raw as? [[String: Any]] {
            return dicts.enumerated().map { idx, d in
                let text = (d["text"] as? String) ?? (d["label"] as? String) ?? "Option \(idx + 1)"
                let id = (d["id"] as? String) ?? "opt-\(idx)"
                let isCorrect = (d["is_correct"] as? Bool)
                    ?? (d["isCorrect"] as? Bool)
                    ?? false
                return FeedMCQOption(id: id, text: text, isCorrect: isCorrect)
            }
        }

        if let boxed = raw as? [Any] {
            return boxed.enumerated().compactMap { idx, el -> FeedMCQOption? in
                if let s = el as? String {
                    let correct = stringContent("correct_answer")
                    return FeedMCQOption(id: "opt-\(idx)", text: s, isCorrect: correct == s)
                }
                if let d = el as? [String: Any] {
                    let text = (d["text"] as? String) ?? "Option \(idx + 1)"
                    let id = (d["id"] as? String) ?? "opt-\(idx)"
                    let isCorrect = (d["is_correct"] as? Bool) ?? (d["isCorrect"] as? Bool) ?? false
                    return FeedMCQOption(id: id, text: text, isCorrect: isCorrect)
                }
                return nil
            }
        }
        return []
    }

    var imageURL: URL? {
        let s = stringContent("file_url")
            ?? stringContent("imageUrl")
            ?? stringContent("thumbnail_url")
            ?? stringContent("thumbnailUrl")
        guard let s, let url = URL(string: s) else { return nil }
        return url
    }

    var linkedConcepts: [String] {
        stringArrayContent("linked_concepts").isEmpty
            ? stringArrayContent("linkedConcepts")
            : stringArrayContent("linked_concepts")
    }

    var keyPoints: [String] {
        let a = stringArrayContent("key_points")
        return a.isEmpty ? stringArrayContent("keyPoints") : a
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

struct DailyActivity: Codable, Sendable, Hashable {
    let date: String
    let reviewsCompleted: Int
    let conceptsLearned: Int
    let notesAdded: Int
    let accuracy: Double

    enum CodingKeys: String, CodingKey {
        case date
        case reviewsCompleted = "reviews_completed"
        case conceptsLearned = "concepts_learned"
        case notesAdded = "notes_added"
        case accuracy
    }

    init(
        date: String,
        reviewsCompleted: Int = 0,
        conceptsLearned: Int = 0,
        notesAdded: Int = 0,
        accuracy: Double = 0
    ) {
        self.date = date
        self.reviewsCompleted = reviewsCompleted
        self.conceptsLearned = conceptsLearned
        self.notesAdded = notesAdded
        self.accuracy = accuracy
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = try c.decode(String.self, forKey: .date)
        reviewsCompleted = try c.decodeIfPresent(Int.self, forKey: .reviewsCompleted) ?? 0
        conceptsLearned = try c.decodeIfPresent(Int.self, forKey: .conceptsLearned) ?? 0
        notesAdded = try c.decodeIfPresent(Int.self, forKey: .notesAdded) ?? 0
        accuracy = try c.decodeIfPresent(Double.self, forKey: .accuracy) ?? 0
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
    let dailyActivity: [DailyActivity]

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
        case dailyActivity = "daily_activity"
    }

    init(
        userId: String? = nil,
        totalConcepts: Int? = nil,
        totalNotes: Int? = nil,
        totalReviews: Int? = nil,
        streakDays: Int? = nil,
        accuracyRate: Double? = nil,
        dueToday: Int? = nil,
        completedToday: Int? = nil,
        dailyGoal: Int? = nil,
        overdue: Int? = nil,
        dailyActivity: [DailyActivity] = []
    ) {
        self.userId = userId
        self.totalConcepts = totalConcepts
        self.totalNotes = totalNotes
        self.totalReviews = totalReviews
        self.streakDays = streakDays
        self.accuracyRate = accuracyRate
        self.dueToday = dueToday
        self.completedToday = completedToday
        self.dailyGoal = dailyGoal
        self.overdue = overdue
        self.dailyActivity = dailyActivity
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        userId = try c.decodeIfPresent(String.self, forKey: .userId)
        totalConcepts = try c.decodeIfPresent(Int.self, forKey: .totalConcepts)
        totalNotes = try c.decodeIfPresent(Int.self, forKey: .totalNotes)
        totalReviews = try c.decodeIfPresent(Int.self, forKey: .totalReviews)
        streakDays = try c.decodeIfPresent(Int.self, forKey: .streakDays)
        accuracyRate = try c.decodeIfPresent(Double.self, forKey: .accuracyRate)
        dueToday = try c.decodeIfPresent(Int.self, forKey: .dueToday)
        completedToday = try c.decodeIfPresent(Int.self, forKey: .completedToday)
        dailyGoal = try c.decodeIfPresent(Int.self, forKey: .dailyGoal)
        overdue = try c.decodeIfPresent(Int.self, forKey: .overdue)
        dailyActivity = try c.decodeIfPresent([DailyActivity].self, forKey: .dailyActivity) ?? []
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
