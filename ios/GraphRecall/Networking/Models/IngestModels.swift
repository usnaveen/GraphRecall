import Foundation

// MARK: - Requests

struct IngestTextRequest: Codable, Sendable {
    let content: String
    let title: String?
    let skipReview: Bool
    let resourceType: String?

    enum CodingKeys: String, CodingKey {
        case content, title
        case skipReview = "skip_review"
        case resourceType = "resource_type"
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(content, forKey: .content)
        try c.encodeIfPresent(title, forKey: .title)
        try c.encode(skipReview, forKey: .skipReview)
        try c.encodeIfPresent(resourceType, forKey: .resourceType)
    }
}

struct IngestURLRequest: Codable, Sendable {
    let url: String
}

struct IngestYouTubeRequest: Codable, Sendable {
    let url: String
    let title: String?
}

struct IngestChatTranscriptRequest: Codable, Sendable {
    let content: String
    let title: String?
}

// MARK: - Responses

struct IngestResponse: Codable, Sendable {
    let noteId: String?
    let conceptIds: [String]
    let flashcardIds: [String]
    let status: String
    let statusReason: String
    let nextAction: String
    let threadId: String
    let error: String?

    enum CodingKeys: String, CodingKey {
        case status, error
        case noteId = "note_id"
        case conceptIds = "concept_ids"
        case flashcardIds = "flashcard_ids"
        case statusReason = "status_reason"
        case nextAction = "next_action"
        case threadId = "thread_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        noteId = try c.decodeIfPresent(String.self, forKey: .noteId)
        let rawIds = try c.decodeIfPresent([String?].self, forKey: .conceptIds) ?? []
        conceptIds = rawIds.compactMap { $0 }
        flashcardIds = try c.decodeIfPresent([String].self, forKey: .flashcardIds) ?? []
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "unknown"
        statusReason = try c.decodeIfPresent(String.self, forKey: .statusReason) ?? status
        nextAction = try c.decodeIfPresent(String.self, forKey: .nextAction) ?? "none"
        threadId = try c.decodeIfPresent(String.self, forKey: .threadId) ?? ""
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }
}

struct IngestYouTubeResponse: Codable, Sendable {
    let noteId: String?
    let status: String
    let resourceType: String?
    let url: String?

    enum CodingKeys: String, CodingKey {
        case status, url
        case noteId = "note_id"
        case resourceType = "resource_type"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        noteId = try c.decodeIfPresent(String.self, forKey: .noteId)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "stored"
        resourceType = try c.decodeIfPresent(String.self, forKey: .resourceType)
        url = try c.decodeIfPresent(String.self, forKey: .url)
    }
}

struct IngestStatusResponse: Codable, Sendable {
    let status: String
    let statusReason: String
    let nextAction: String
    let threadId: String
    let stage: String?
    let noteId: String?
    let nextStep: String?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case status, stage, error
        case statusReason = "status_reason"
        case nextAction = "next_action"
        case threadId = "thread_id"
        case noteId = "note_id"
        case nextStep = "next_step"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "not_found"
        statusReason = try c.decodeIfPresent(String.self, forKey: .statusReason) ?? status
        nextAction = try c.decodeIfPresent(String.self, forKey: .nextAction) ?? "none"
        threadId = try c.decodeIfPresent(String.self, forKey: .threadId) ?? ""
        stage = try c.decodeIfPresent(String.self, forKey: .stage)
        noteId = try c.decodeIfPresent(String.self, forKey: .noteId)
        nextStep = try c.decodeIfPresent(String.self, forKey: .nextStep)
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }
}
