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
    let warnings: [String]

    enum CodingKeys: String, CodingKey {
        case status, error, warnings
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
        warnings = try c.decodeIfPresent([String].self, forKey: .warnings) ?? []
    }
}

struct IngestYouTubeResponse: Codable, Sendable {
    let noteId: String?
    let status: String
    let resourceType: String?
    let url: String?
    let title: String?
    /// "captions" | "auto_captions" | "gemini" | "none" (older servers omit it: link stored only).
    let transcriptSource: String?
    let conceptIds: [String]
    let warnings: [String]

    enum CodingKeys: String, CodingKey {
        case status, url, title, warnings
        case noteId = "note_id"
        case resourceType = "resource_type"
        case transcriptSource = "transcript_source"
        case conceptIds = "concept_ids"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        noteId = try c.decodeIfPresent(String.self, forKey: .noteId)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "stored"
        resourceType = try c.decodeIfPresent(String.self, forKey: .resourceType)
        url = try c.decodeIfPresent(String.self, forKey: .url)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        transcriptSource = try c.decodeIfPresent(String.self, forKey: .transcriptSource)
        conceptIds = (try? c.decodeIfPresent([String].self, forKey: .conceptIds)) ?? []
        warnings = (try? c.decodeIfPresent([String].self, forKey: .warnings)) ?? []
    }

    /// True when the transcript was read into the graph, not just the link saved.
    /// Older servers answer "stored" for every link; new ones only when no transcript could be had.
    var wasRead: Bool { status != "stored" }

    /// One line for toasts and the import history.
    var summary: String {
        guard wasRead else { return "Link saved: no transcript available" }
        guard let transcriptSource else { return "Already in your library" }  // repeat share: nothing re-read
        let via = transcriptSource == "gemini" ? "transcribed by Gemini" : "from captions"
        return conceptIds.isEmpty ? "Transcript imported (\(via))" : "\(conceptIds.count) concepts (\(via))"
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

/// `POST /api/v2/ingest/document/extract`: a document's text, OCR'd where it had no text layer.
struct DocumentExtractResponse: Codable, Sendable {
    let markdown: String
    let pages: Int
    let ocrPages: [Int]
    let method: String
    let warnings: [String]

    enum CodingKeys: String, CodingKey {
        case markdown, pages, method, warnings
        case ocrPages = "ocr_pages"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        markdown = try c.decodeIfPresent(String.self, forKey: .markdown) ?? ""
        pages = try c.decodeIfPresent(Int.self, forKey: .pages) ?? 0
        ocrPages = try c.decodeIfPresent([Int].self, forKey: .ocrPages) ?? []
        method = try c.decodeIfPresent(String.self, forKey: .method) ?? "native"
        warnings = try c.decodeIfPresent([String].self, forKey: .warnings) ?? []
    }
}
