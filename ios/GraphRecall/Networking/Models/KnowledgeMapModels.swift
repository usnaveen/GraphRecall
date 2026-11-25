import SwiftUI

// Knowledge map of the person (/api/knowledge-map), capability profile and resume (/api/profile),
// and map-the-territory answers (/api/territory).

enum KnowledgeStatus: String, Codable, CaseIterable, Identifiable, Sendable {
    case strong, shaky, seen, unexposed
    var id: String { rawValue }

    var title: String {
        switch self {
        case .strong: return "Strong"
        case .shaky: return "Shaky"
        case .seen: return "Seen"
        case .unexposed: return "New to you"
        }
    }

    /// Fits the compact tiles.
    var shortTitle: String { self == .unexposed ? "New" : title }

    var explanation: String {
        switch self {
        case .strong: return "Tested well, or backed by coursework, projects or your own rating"
        case .shaky: return "You struggled when tested, or rated yourself low"
        case .seen: return "Studied or claimed, never tested"
        case .unexposed: return "No sign you've met this yet"
        }
    }

    var color: Color {
        switch self {
        case .strong: return GRColor.success
        case .shaky: return GRColor.amber
        case .seen: return GRColor.accentCyan
        case .unexposed: return GRColor.textTertiary
        }
    }

    var systemImage: String {
        switch self {
        case .strong: return "checkmark.seal.fill"
        case .shaky: return "exclamationmark.triangle.fill"
        case .seen: return "eye.fill"
        case .unexposed: return "questionmark.circle"
        }
    }
}

struct KnowledgeAssessment: Decodable, Identifiable, Hashable, Sendable {
    var id: String { key + (conceptId ?? "") }
    let name: String
    let key: String
    let status: KnowledgeStatus
    let mastery: Double?
    let confidence: Double?
    let basis: String?
    let conceptId: String?
    let conceptName: String?
    let domain: String?
    let selfRating: Int?
    let evidence: [String: Int]?
    let lastEvidenceAt: String?

    enum CodingKeys: String, CodingKey {
        case name, key, status, mastery, confidence, basis, domain, evidence
        case conceptId = "concept_id"
        case conceptName = "concept_name"
        case selfRating = "self_rating"
        case lastEvidenceAt = "last_evidence_at"
    }

    var basisLabel: String {
        switch basis {
        case "tested": return "From your reviews"
        case "coursework": return "From courses and projects"
        case "self-reported": return "Your own rating"
        case "studied": return "In your notes, not tested"
        case "claimed": return "On your resume, not tested"
        default: return "No evidence yet"
        }
    }

    /// Human-readable evidence list, e.g. "3 reviews · 1 course".
    var evidenceSummary: String {
        let labels: [String: String] = [
            "review": "review", "quiz": "quiz", "territory": "territory card", "leetcode": "LeetCode attempt",
            "course": "course", "project": "project", "self_rating": "self-rating", "resume": "resume mention",
            "agent": "agent note", "in_graph": "in your graph",
        ]
        let parts = (evidence ?? [:]).sorted { $0.key < $1.key }.compactMap { k, n -> String? in
            guard let label = labels[k] else { return nil }
            if k == "in_graph" { return label }
            return "\(n) \(label)\(n == 1 ? "" : "s")"
        }
        return parts.isEmpty ? "No evidence yet" : parts.joined(separator: " · ")
    }
}

struct KnowledgeAssessResponse: Decodable, Sendable {
    let results: [KnowledgeAssessment]
}

struct KnowledgeSummary: Decodable, Sendable {
    let counts: [String: Int]
    let domains: [String: [String: Int]]
    let strongest: [KnowledgeAssessment]
    let weakest: [KnowledgeAssessment]
    let items: [KnowledgeAssessment]?

    func count(_ s: KnowledgeStatus) -> Int { counts[s.rawValue] ?? 0 }
    var total: Int { KnowledgeStatus.allCases.reduce(0) { $0 + count($1) } }
}

struct ExposureLevel: Decodable, Hashable, Sendable {
    let level: Int
    let label: String
}

struct ExposureQuestion: Decodable, Identifiable, Hashable, Sendable {
    var id: String { name }
    let name: String
    let status: KnowledgeStatus
    let sources: [String]
    let prompt: String
    let levels: [ExposureLevel]

    var sourceLabel: String {
        if sources.contains("resume") { return "On your resume" }
        if sources.contains("agent") { return "An agent asked about it" }
        if sources.contains("course") { return "From a course" }
        if sources.contains("project") { return "From a project" }
        return ""
    }
}

struct ExposureQuestionsResponse: Decodable, Sendable {
    let questions: [ExposureQuestion]
}

struct SelfRatingBody: Encodable, Sendable {
    let name: String
    let level: Int
}

struct AssessBody: Encodable, Sendable {
    let names: [String]
}

// MARK: - Profile

struct UserProfileInfo: Codable, Sendable, Equatable {
    var headline: String?
    var educationStatus: String?
    var institution: String?
    var program: String?
    var graduationYear: Int?
    var goals: String?

    enum CodingKeys: String, CodingKey {
        case headline, institution, program, goals
        case educationStatus = "education_status"
        case graduationYear = "graduation_year"
    }

    static let empty = UserProfileInfo()
}

struct UserCourse: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let code: String?
    let name: String
    let term: String?
    let grade: String?
    let institution: String?
    let topics: [String]
}

struct UserCoursesResponse: Decodable, Sendable { let courses: [UserCourse] }

struct CourseBody: Encodable, Sendable {
    let name: String
    let code: String?
    let term: String?
    let grade: String?
    let institution: String?
    let topics: [String]
}

struct UserProject: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let name: String
    let summary: String?
    let url: String?
    let skills: [String]
    let started: String?
    let ended: String?
}

struct UserProjectsResponse: Decodable, Sendable { let projects: [UserProject] }

struct ProjectBody: Encodable, Sendable {
    let name: String
    let summary: String?
    let url: String?
    let skills: [String]
    let started: String?
    let ended: String?
}

// MARK: - Resume

struct ResumeSkill: Decodable, Identifiable, Hashable, Sendable {
    var id: String { key }
    let name: String
    let key: String
    let section: String?
    let status: KnowledgeStatus
    let mastery: Double?
    let basis: String?
    let conceptId: String?
    let selfRating: Int?
    let spans: [[Int]]

    enum CodingKeys: String, CodingKey {
        case name, key, section, status, mastery, basis, spans
        case conceptId = "concept_id"
        case selfRating = "self_rating"
    }
}

struct ResumeOverview: Decodable, Sendable {
    let id: String?
    let fileName: String?
    let text: String?
    let skills: [ResumeSkill]?
    let counts: [String: Int]?
    let createdAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, text, skills, counts
        case fileName = "file_name"
        case createdAt = "created_at"
    }

    var isEmpty: Bool { (text ?? "").isEmpty }
}

struct ResumeUploadBody: Encodable, Sendable {
    let text: String
    let fileName: String?
    enum CodingKeys: String, CodingKey {
        case text
        case fileName = "file_name"
    }
}

// MARK: - Territory

struct TerritoryMatch: Decodable, Hashable, Sendable {
    let id: String?
    let name: String
    let said: String?
}

struct TerritoryResult: Decodable, Sendable {
    let matched: [TerritoryMatch]
    let missed: [TerritoryMatch]
    let extras: [String]
    let score: Double
    let suggestedDifficulty: String
    let total: Int

    enum CodingKeys: String, CodingKey {
        case matched, missed, extras, score, total
        case suggestedDifficulty = "suggested_difficulty"
    }
}

struct TerritoryAnswerBody: Encodable, Sendable { let answer: String }
