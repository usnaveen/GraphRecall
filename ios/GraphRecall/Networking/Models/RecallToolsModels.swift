import Foundation

// Models for "show me this later" (/api/later), LeetCode recall (/api/leetcode) and
// structure cards (/api/notes/{id}/structure-cards).

// MARK: - Later

struct LaterItem: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let text: String
    let url: String?
    let source: String?
    let whenPhrase: String?
    let showAt: Date?
    let shownAt: Date?
    let createdAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, text, url, source
        case whenPhrase = "when_phrase"
        case showAt = "show_at"
        case shownAt = "shown_at"
        case createdAt = "created_at"
    }

    var link: URL? { url.flatMap(URL.init(string:)) }
    var isDue: Bool { (showAt ?? .distantFuture) <= Date() }
}

struct LaterListResponse: Decodable, Sendable {
    let items: [LaterItem]
}

struct LaterCreateBody: Encodable, Sendable {
    let text: String
    let url: String?
    let when: String?
    let tz: String
    let source: String
}

struct LaterSnoozeBody: Encodable, Sendable {
    let when: String
    let tz: String
}

/// Quick picks shown as chips; the backend also parses these phrases out of typed/dictated text.
enum LaterWhen: String, CaseIterable, Identifiable, Sendable {
    case laterToday = "later today"
    case tonight
    case tomorrow
    case weekend = "this weekend"
    case nextWeek = "next week"

    var id: String { rawValue }
    var title: String {
        switch self {
        case .laterToday: return "Later today"
        case .tonight: return "Tonight"
        case .tomorrow: return "Tomorrow"
        case .weekend: return "Weekend"
        case .nextWeek: return "Next week"
        }
    }
}

// MARK: - LeetCode

enum CodingOutcome: String, CaseIterable, Identifiable, Codable, Sendable {
    case solved, hint, failed
    var id: String { rawValue }
    var title: String {
        switch self {
        case .solved: return "Solved"
        case .hint: return "Needed a hint"
        case .failed: return "Couldn’t solve"
        }
    }
    var tone: GRTone {
        switch self {
        case .solved: return .success
        case .hint: return .amber
        case .failed: return .coral
        }
    }
}

enum MistakeTag: String, CaseIterable, Identifiable, Codable, Sendable {
    case wrongPattern = "wrong_pattern"
    case edgeCase = "edge_case"
    case offByOne = "off_by_one"
    case complexity
    case bug
    case forgot
    case other
    var id: String { rawValue }
    var title: String {
        switch self {
        case .wrongPattern: return "Wrong pattern"
        case .edgeCase: return "Edge case"
        case .offByOne: return "Off-by-one"
        case .complexity: return "Too slow"
        case .bug: return "Bug"
        case .forgot: return "Forgot approach"
        case .other: return "Other"
        }
    }
}

enum CodingDifficulty: String, CaseIterable, Identifiable, Codable, Sendable {
    case easy, medium, hard
    var id: String { rawValue }
    var title: String { rawValue.capitalized }
    var tone: GRTone {
        switch self {
        case .easy: return .success
        case .medium: return .amber
        case .hard: return .coral
        }
    }
}

struct CodingProblemSummary: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let title: String
    let difficulty: String?
    let pattern: String?
    let url: String?
    let attempts: Int
    let failed: Int
    let lastOutcome: String?
    let updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, title, difficulty, pattern, url, attempts, failed
        case lastOutcome = "last_outcome"
        case updatedAt = "updated_at"
    }
}

struct CodingProblemsResponse: Decodable, Sendable {
    let problems: [CodingProblemSummary]
}

struct CodingAttempt: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let outcome: String
    let mistake: String?
    let mistakeTag: String?
    let minutes: Int?
    let createdAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, outcome, mistake, minutes
        case mistakeTag = "mistake_tag"
        case createdAt = "created_at"
    }
}

struct RecallCardPreview: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let front: String
    let back: String
}

struct CodingProblemDetail: Decodable, Identifiable, Sendable {
    let id: String
    let title: String
    let url: String?
    let difficulty: String?
    let pattern: String?
    let keyInsight: String?
    let pseudocode: String?
    let complexity: String?
    let attempts: [CodingAttempt]?
    let cards: [RecallCardPreview]?

    enum CodingKeys: String, CodingKey {
        case id, title, url, difficulty, pattern, pseudocode, complexity, attempts, cards
        case keyInsight = "key_insight"
    }
}

struct CodingProblemBody: Encodable, Sendable {
    let title: String
    let url: String?
    let difficulty: String?
    let pattern: String?
    let keyInsight: String?
    let pseudocode: String?
    let complexity: String?

    enum CodingKeys: String, CodingKey {
        case title, url, difficulty, pattern, pseudocode, complexity
        case keyInsight = "key_insight"
    }
}

struct CodingProblemSaved: Decodable, Sendable {
    let id: String
    let cardIds: [String]

    enum CodingKeys: String, CodingKey {
        case id
        case cardIds = "card_ids"
    }
}

struct CodingAttemptBody: Encodable, Sendable {
    let outcome: String
    let mistake: String?
    let mistakeTag: String?
    let minutes: Int?

    enum CodingKeys: String, CodingKey {
        case outcome, mistake, minutes
        case mistakeTag = "mistake_tag"
    }
}

struct CodingAttemptLogged: Decodable, Sendable {
    let cardIds: [String]
    let dueNow: Bool

    enum CodingKeys: String, CodingKey {
        case cardIds = "card_ids"
        case dueNow = "due_now"
    }
}

struct WeakSpot: Decodable, Identifiable, Hashable, Sendable {
    var id: String { "\(tag)|\(pattern)" }
    let tag: String
    let pattern: String
    let n: Int
    let label: String
}

struct WeakSpotsResponse: Decodable, Sendable {
    let weakSpots: [WeakSpot]
    enum CodingKeys: String, CodingKey { case weakSpots = "weak_spots" }
}

// MARK: - Structure cards

struct StructureCardsResponse: Decodable, Sendable {
    let cardIds: [String]
    let count: Int?
    let reason: String?

    enum CodingKeys: String, CodingKey {
        case count, reason
        case cardIds = "card_ids"
    }
}
