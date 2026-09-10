import Foundation

struct ConceptDumpRequest: Codable, Sendable {
    let concepts: [String]
}

struct ConceptDumpSource: Codable, Sendable, Identifiable, Hashable {
    var id: String { url.isEmpty ? title : url }
    let title: String
    let url: String
    let snippet: String

    enum CodingKeys: String, CodingKey { case title, url, snippet }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        url = try c.decodeIfPresent(String.self, forKey: .url) ?? ""
        snippet = try c.decodeIfPresent(String.self, forKey: .snippet) ?? ""
    }
}

struct ConceptDumpCard: Codable, Sendable, Hashable {
    let id: String
    let type: String
    let front: String?
}

struct ConceptDumpItemResult: Codable, Sendable, Identifiable, Hashable {
    var id: String { conceptId ?? concept }
    let concept: String
    let conceptId: String?
    let status: String
    let error: String?
    let sources: [ConceptDumpSource]
    let noteId: String?
    let cards: [ConceptDumpCard]

    enum CodingKeys: String, CodingKey {
        case concept
        case conceptId = "concept_id"
        case status, error, sources, cards
        case noteId = "note_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        concept = try c.decode(String.self, forKey: .concept)
        conceptId = try c.decodeIfPresent(String.self, forKey: .conceptId)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "ok"
        error = try c.decodeIfPresent(String.self, forKey: .error)
        sources = try c.decodeIfPresent([ConceptDumpSource].self, forKey: .sources) ?? []
        noteId = try c.decodeIfPresent(String.self, forKey: .noteId)
        cards = try c.decodeIfPresent([ConceptDumpCard].self, forKey: .cards) ?? []
    }
}

struct ConceptDumpResponse: Codable, Sendable {
    let status: String
    let requested: Int
    let processed: Int
    let succeeded: Int
    let results: [ConceptDumpItemResult]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "complete"
        requested = try c.decodeIfPresent(Int.self, forKey: .requested) ?? 0
        processed = try c.decodeIfPresent(Int.self, forKey: .processed) ?? 0
        succeeded = try c.decodeIfPresent(Int.self, forKey: .succeeded) ?? 0
        results = try c.decodeIfPresent([ConceptDumpItemResult].self, forKey: .results) ?? []
    }

    enum CodingKeys: String, CodingKey {
        case status, requested, processed, succeeded, results
    }
}
