import Foundation

/// Note / book row from `GET /api/notes`.
struct LibraryNote: Codable, Identifiable, Hashable, Sendable {
    let id: String
    let title: String?
    let contentText: String?
    let resourceType: String?
    let sourceURL: String?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, title
        case contentText = "content_text"
        case resourceType = "resource_type"
        case sourceURL = "source_url"
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
        contentText = try c.decodeIfPresent(String.self, forKey: .contentText)
        resourceType = try c.decodeIfPresent(String.self, forKey: .resourceType)
        sourceURL = try c.decodeIfPresent(String.self, forKey: .sourceURL)
        createdAt = try c.decodeIfPresent(String.self, forKey: .createdAt)
    }

    var displayTitle: String {
        let t = title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return t.isEmpty ? "Untitled Book" : t
    }

    var wordCount: Int {
        guard let text = contentText, !text.isEmpty else { return 0 }
        return text.split { $0.isWhitespace || $0.isNewline }.count
    }

    var estimatedReadTime: String {
        let minutes = max(1, Int((Double(wordCount) / 200.0).rounded()))
        if minutes < 60 { return "\(minutes) min" }
        let hours = minutes / 60
        let remain = minutes % 60
        return remain > 0 ? "\(hours)h \(remain)m" : "\(hours)h"
    }

    /// Markdown `#` / `##` headings — mirrors web `extractChapters`.
    var chapters: [String] {
        guard let content = contentText else { return [] }
        var result: [String] = []
        for line in content.split(separator: "\n", omittingEmptySubsequences: false) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard trimmed.hasPrefix("# ") || trimmed.hasPrefix("## ") else { continue }
            let heading = trimmed.replacingOccurrences(
                of: #"^#{1,2}\s+"#,
                with: "",
                options: .regularExpression
            )
            if heading.count > 2 && heading.count < 120 {
                result.append(heading)
            }
            if result.count >= 30 { break }
        }
        return result
    }
}

struct NotesListResponse: Codable, Sendable {
    let notes: [LibraryNote]
    let total: Int
    let limit: Int
    let offset: Int

    enum CodingKeys: String, CodingKey {
        case notes, total, limit, offset
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        notes = try c.decodeIfPresent([LibraryNote].self, forKey: .notes) ?? []
        total = try c.decodeIfPresent(Int.self, forKey: .total) ?? notes.count
        limit = try c.decodeIfPresent(Int.self, forKey: .limit) ?? 50
        offset = try c.decodeIfPresent(Int.self, forKey: .offset) ?? 0
    }
}

/// Queued response from `POST /api/v2/ingest/processed-zip`.
struct ProcessedZipIngestResponse: Codable, Sendable {
    let status: String
    let statusReason: String
    let nextAction: String
    let threadId: String
    let message: String
    let noteId: String?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case status, message, error
        case statusReason = "status_reason"
        case nextAction = "next_action"
        case threadId = "thread_id"
        case noteId = "note_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "processing"
        statusReason = try c.decodeIfPresent(String.self, forKey: .statusReason) ?? "queued"
        nextAction = try c.decodeIfPresent(String.self, forKey: .nextAction) ?? "none"
        threadId = try c.decodeIfPresent(String.self, forKey: .threadId) ?? ""
        message = try c.decodeIfPresent(String.self, forKey: .message) ?? ""
        noteId = try c.decodeIfPresent(String.self, forKey: .noteId)
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }
}

extension Notification.Name {
    /// Switch to Profile and push Library (Create success deep link).
    static let grNavigateLibrary = Notification.Name("gr.navigate.library")
    /// Switch to Feed tab (Graph quiz / Assistant create-card handoff).
    static let grNavigateFeed = Notification.Name("gr.navigate.feed")
}
