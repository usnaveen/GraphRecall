import Foundation

// MARK: - Graph search / focus

struct GraphSearchResponse: Decodable, Sendable {
    let results: [GraphSearchResult]
}

struct GraphSearchResult: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let name: String
    let domain: String?
    let color: String?
}

struct ConceptFocusResponse: Decodable, Sendable {
    let center: FocusConcept
    let connections: [FocusConnection]
    let totalConnections: Int?

    enum CodingKeys: String, CodingKey {
        case center, connections
        case totalConnections = "total_connections"
    }
}

struct FocusConcept: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let name: String
    let definition: String?
    let domain: String?
    let complexityScore: Double?
    let masteryLevel: Double?
    let color: String?

    enum CodingKeys: String, CodingKey {
        case id, name, definition, domain, color
        case complexityScore = "complexity_score"
        case masteryLevel = "mastery_level"
    }
}

struct FocusConnection: Decodable, Identifiable, Hashable, Sendable {
    let concept: FocusConcept
    let relationship: String?
    let direction: String?
    let strength: Double?

    var id: String { "\(concept.id)-\(relationship ?? "")-\(direction ?? "")" }
}

// MARK: - Links / merge

struct LinkSuggestionsResponse: Decodable, Sendable {
    let links: [LinkSuggestion]
}

struct LinkSuggestion: Codable, Identifiable, Hashable, Sendable {
    let targetId: String
    let targetName: String?
    let relationshipType: String
    let strength: Double?
    let reason: String?

    var id: String { "\(targetId)-\(relationshipType)" }

    enum CodingKeys: String, CodingKey {
        case strength, reason
        case targetId = "target_id"
        case targetName = "target_name"
        case relationshipType = "relationship_type"
    }
}

struct ApplyLinksBody: Encodable, Sendable {
    let links: [LinkSuggestion]
}

struct MergeConceptsBody: Encodable, Sendable {
    let sourceIds: [String]
    let targetId: String

    enum CodingKeys: String, CodingKey {
        case sourceIds = "source_ids"
        case targetId = "target_id"
    }
}

// MARK: - Human-in-the-loop import review

struct ReviewIngestBody: Encodable, Sendable {
    let content: String
    let sourceURL: String?
    let skipReview: Bool

    enum CodingKeys: String, CodingKey {
        case content
        case sourceURL = "source_url"
        case skipReview = "skip_review"
    }
}

struct ReviewIngestResponse: Decodable, Sendable {
    let noteId: String
    let sessionId: String?
    let conceptsCount: Int
    let status: String
    let message: String

    enum CodingKeys: String, CodingKey {
        case status, message
        case noteId = "note_id"
        case sessionId = "session_id"
        case conceptsCount = "concepts_count"
    }
}

struct ConceptReviewItem: Codable, Identifiable, Hashable, Sendable {
    let id: String
    var name: String
    var definition: String
    var domain: String
    let complexityScore: Double
    let confidence: Double
    let relatedConcepts: [String]
    let prerequisites: [String]
    var isSelected: Bool
    let isDuplicate: Bool
    let matchedExistingId: String?
    var userModified: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, definition, domain, confidence, prerequisites
        case complexityScore = "complexity_score"
        case relatedConcepts = "related_concepts"
        case isSelected = "is_selected"
        case isDuplicate = "is_duplicate"
        case matchedExistingId = "matched_existing_id"
        case userModified = "user_modified"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        definition = try c.decodeIfPresent(String.self, forKey: .definition) ?? ""
        domain = try c.decodeIfPresent(String.self, forKey: .domain) ?? "General"
        complexityScore = try c.decodeIfPresent(Double.self, forKey: .complexityScore) ?? 5
        confidence = try c.decodeIfPresent(Double.self, forKey: .confidence) ?? 0.5
        relatedConcepts = try c.decodeIfPresent([String].self, forKey: .relatedConcepts) ?? []
        prerequisites = try c.decodeIfPresent([String].self, forKey: .prerequisites) ?? []
        isSelected = try c.decodeIfPresent(Bool.self, forKey: .isSelected) ?? true
        isDuplicate = try c.decodeIfPresent(Bool.self, forKey: .isDuplicate) ?? false
        matchedExistingId = try c.decodeIfPresent(String.self, forKey: .matchedExistingId)
        userModified = try c.decodeIfPresent(Bool.self, forKey: .userModified) ?? false
    }
}

struct ConceptReviewSession: Decodable, Sendable {
    let sessionId: String
    let noteId: String
    let concepts: [ConceptReviewItem]
    let status: String?

    enum CodingKeys: String, CodingKey {
        case concepts, status
        case sessionId = "session_id"
        case noteId = "note_id"
    }
}

struct ConceptReviewApprovalBody: Encodable, Sendable {
    let sessionId: String
    let approvedConcepts: [ConceptReviewItem]
    let removedConceptIds: [String]
    let addedConcepts: [ConceptReviewItem]

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case approvedConcepts = "approved_concepts"
        case removedConceptIds = "removed_concept_ids"
        case addedConcepts = "added_concepts"
    }
}

struct PendingReviewSessionsResponse: Decodable, Sendable {
    let sessions: [PendingReviewSession]
}

struct PendingReviewSession: Decodable, Identifiable, Hashable, Sendable {
    let sessionId: String
    let noteId: String?
    let conceptsCount: Int
    let createdAt: String?

    var id: String { sessionId }

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case noteId = "note_id"
        case conceptsCount = "concepts_count"
        case createdAt = "created_at"
    }
}

// MARK: - Saved items / knowledge summary

struct SavedItemsResponse: Decodable, Sendable {
    let items: [SavedItem]
    let total: Int
}

struct SavedItem: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let type: String?
    let questionText: String?
    let frontContent: String?
    let backContent: String?
    let correctAnswer: String?
    let explanation: String?
    let topic: String?
    let createdAt: String?
    let itemCategory: String?

    var displayTitle: String { questionText ?? frontContent ?? "Saved card" }
    var displayAnswer: String? { backContent ?? correctAnswer }

    enum CodingKeys: String, CodingKey {
        case id, type, explanation, topic
        case questionText = "question_text"
        case frontContent = "front_content"
        case backContent = "back_content"
        case correctAnswer = "correct_answer"
        case createdAt = "created_at"
        case itemCategory = "item_category"
    }
}

struct KnowledgeSummaryResponse: Decodable, Sendable {
    let domains: [KnowledgeDomainStat]
    let totalConcepts: Int?
    let totalRelationships: Int?

    enum CodingKeys: String, CodingKey {
        case domains
        case totalConcepts = "total_concepts"
        case totalRelationships = "total_relationships"
    }
}

struct KnowledgeDomainStat: Decodable, Hashable, Sendable {
    let domain: String?
    let conceptCount: Int
    let avgConfidence: Double?

    enum CodingKeys: String, CodingKey {
        case domain
        case conceptCount = "concept_count"
        case avgConfidence = "avg_confidence"
    }
}
