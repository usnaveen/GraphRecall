import Foundation

// MARK: - Recall schedule (GET /api/feed/schedule)

struct ScheduleDay: Codable, Identifiable, Hashable, Sendable {
    var id: String { date }
    let date: String
    let count: Int
    let topics: [String]

    enum CodingKeys: String, CodingKey {
        case date, count, topics
    }

    init(date: String, count: Int = 0, topics: [String] = []) {
        self.date = date
        self.count = count
        self.topics = topics
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = try c.decode(String.self, forKey: .date)
        if let i = try? c.decode(Int.self, forKey: .count) {
            count = i
        } else if let d = try? c.decode(Double.self, forKey: .count) {
            count = Int(d)
        } else {
            count = 0
        }
        topics = try c.decodeIfPresent([String].self, forKey: .topics) ?? []
    }
}

// MARK: - Uploads (GET /api/uploads)

struct ProfileUpload: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let title: String?
    let description: String?
    let fileURL: String?
    let thumbnailURL: String?
    let uploadType: String?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, title, description
        case fileURL = "file_url"
        case thumbnailURL = "thumbnail_url"
        case uploadType = "upload_type"
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
        title = try c.decodeIfPresent(String.self, forKey: .title)
        description = try c.decodeIfPresent(String.self, forKey: .description)
        fileURL = try c.decodeIfPresent(String.self, forKey: .fileURL)
        thumbnailURL = try c.decodeIfPresent(String.self, forKey: .thumbnailURL)
        uploadType = try c.decodeIfPresent(String.self, forKey: .uploadType)
        if let s = try? c.decode(String.self, forKey: .createdAt) {
            createdAt = s
        } else {
            createdAt = nil
        }
    }

    var displayTitle: String {
        if let title, !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return title
        }
        if let fileURL, let last = fileURL.split(separator: "/").last {
            let name = last.split(separator: "?").first.map(String.init) ?? String(last)
            if !name.isEmpty { return name }
        }
        return "Untitled Upload"
    }
}

struct UploadsListResponse: Codable, Sendable {
    let uploads: [ProfileUpload]
    let total: Int
    let limit: Int
    let offset: Int

    enum CodingKeys: String, CodingKey {
        case uploads, total, limit, offset
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        uploads = try c.decodeIfPresent([ProfileUpload].self, forKey: .uploads) ?? []
        total = try c.decodeIfPresent(Int.self, forKey: .total) ?? uploads.count
        limit = try c.decodeIfPresent(Int.self, forKey: .limit) ?? 20
        offset = try c.decodeIfPresent(Int.self, forKey: .offset) ?? 0
    }
}

// MARK: - Quiz history (GET /api/feed/history/quizzes)

struct QuizHistoryItem: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let questionText: String?
    let questionType: String?
    let correctAnswer: String?
    let topic: String?
    let conceptId: String?
    let createdAt: String?
    let frontContent: String?
    let backContent: String?

    enum CodingKeys: String, CodingKey {
        case id, topic
        case questionText = "question_text"
        case questionType = "question_type"
        case correctAnswer = "correct_answer"
        case conceptId = "concept_id"
        case createdAt = "created_at"
        case frontContent = "front_content"
        case backContent = "back_content"
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
        questionText = try c.decodeIfPresent(String.self, forKey: .questionText)
        questionType = try c.decodeIfPresent(String.self, forKey: .questionType)
        correctAnswer = try c.decodeIfPresent(String.self, forKey: .correctAnswer)
        topic = try c.decodeIfPresent(String.self, forKey: .topic)
        conceptId = try c.decodeIfPresent(String.self, forKey: .conceptId)
        if let s = try? c.decode(String.self, forKey: .createdAt) {
            createdAt = s
        } else {
            createdAt = nil
        }
        frontContent = try c.decodeIfPresent(String.self, forKey: .frontContent)
        backContent = try c.decodeIfPresent(String.self, forKey: .backContent)
    }

    var displayQuestion: String {
        let q = questionText?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !q.isEmpty { return q }
        let front = frontContent?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return front.isEmpty ? "Question" : front
    }

    var displayAnswer: String {
        if let a = correctAnswer, !a.isEmpty { return a }
        if let b = backContent, !b.isEmpty { return b }
        return "Check options"
    }

    var topicKey: String {
        let t = topic?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return t.isEmpty ? "General" : t
    }
}

struct QuizHistoryResponse: Codable, Sendable {
    let quizzes: [QuizHistoryItem]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        quizzes = try c.decodeIfPresent([QuizHistoryItem].self, forKey: .quizzes) ?? []
    }

    enum CodingKeys: String, CodingKey { case quizzes }
}

// MARK: - Profile concept row (mapped from graph3d nodes)

struct ProfileConcept: Identifiable, Hashable, Sendable {
    let id: String
    let name: String
    let definition: String
    let domain: String
    let complexityScore: Int

    init(from node: GraphNode) {
        id = node.id
        name = node.name
        definition = node.definition ?? ""
        domain = node.domain ?? "General"
        let score = node.complexityScore ?? node.size ?? 5
        complexityScore = Int(score.rounded())
    }
}
