import Foundation

/// State shared between the app, the Today widget and the share extension through the App Group.
enum GRShared {
    static let appGroup = "group.com.usnaveen.graphrecall"
    static let urlScheme = "graphrecall"

    static var defaults: UserDefaults {
        UserDefaults(suiteName: appGroup) ?? .standard
    }

    static var containerURL: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)
    }
}

/// Auth/endpoint snapshot shared with `GraphRecallShare` so direct background uploads authenticate cleanly.
enum GRSharedAuth {
    private static let apiBaseKey = "shared.auth.apiBaseURL"
    private static let tokenKey = "shared.auth.bearerToken"

    static var apiBaseURL: String? {
        GRShared.defaults.string(forKey: apiBaseKey)
    }

    static var bearerToken: String? {
        GRShared.defaults.string(forKey: tokenKey)
    }

    static func sync(apiBaseURL: String, bearerToken: String?) {
        GRShared.defaults.set(apiBaseURL, forKey: apiBaseKey)
        if let bearerToken, !bearerToken.isEmpty {
            GRShared.defaults.set(bearerToken, forKey: tokenKey)
        } else {
            GRShared.defaults.removeObject(forKey: tokenKey)
        }
    }

    static func clear() {
        GRShared.defaults.removeObject(forKey: apiBaseKey)
        GRShared.defaults.removeObject(forKey: tokenKey)
    }
}

/// Normalizes links across Safari, custom domains, and Substack mobile share sheets.
enum GRShareURLNormalizer {
    static func extractURL(from raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        // Handle bare Substack links such as `substack.com/inbox/post/<id>` without a scheme.
        if !trimmed.contains(where: \.isWhitespace) {
            if let direct = canonicalCandidate(trimmed) {
                return direct
            }
        }

        // Handle share sheets that bundle title/snippet text alongside an embedded URL.
        if let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) {
            let range = NSRange(trimmed.startIndex..<trimmed.endIndex, in: trimmed)
            let matches = detector.matches(in: trimmed, options: [], range: range)
            for match in matches {
                guard let url = match.url,
                      let scheme = url.scheme?.lowercased(),
                      scheme == "http" || scheme == "https" else {
                    continue
                }
                return url.absoluteString
            }
        }
        return nil
    }

    private static func canonicalCandidate(_ token: String) -> String? {
        if let url = URL(string: token),
           let scheme = url.scheme?.lowercased(),
           (scheme == "http" || scheme == "https"),
           url.host != nil {
            return token
        }
        if token.lowercased().hasPrefix("substack.com/")
            || token.lowercased().contains(".substack.com/") {
            let withScheme = "https://\(token)"
            if let url = URL(string: withScheme), url.host != nil {
                return withScheme
            }
        }
        return nil
    }
}

/// Shared background URLSession identifiers and payload file helpers for the Share extension.
enum GRShareUploadConfig {
    static let backgroundSessionId = "com.usnaveen.graphrecall.share.upload"

    static func payloadFileURL(for id: UUID) -> URL? {
        guard let root = GRShared.containerURL else { return nil }
        let dir = root.appendingPathComponent("share-uploads", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("\(id.uuidString).json")
    }

    static func removePayloadFile(for id: UUID) {
        guard let fileURL = payloadFileURL(for: id) else { return }
        try? FileManager.default.removeItem(at: fileURL)
    }
}

/// What the widget shows — written by the app whenever Today loads or a card is graded.
struct GRReviewSnapshot: Codable, Equatable, Sendable {
    var dueCount: Int
    var completedToday: Int
    var dailyGoal: Int
    var streak: Int
    var upNext: [String]
    var isDemo: Bool
    var updatedAt: Date

    static let storageKey = "widget.reviewSnapshot"

    static let placeholder = GRReviewSnapshot(
        dueCount: 12,
        completedToday: 8,
        dailyGoal: 20,
        streak: 5,
        upNext: ["Attention heads", "Graph traversal", "Spaced repetition"],
        isDemo: true,
        updatedAt: .now
    )

    /// Before the app has ever synced.
    static let empty = GRReviewSnapshot(
        dueCount: 0,
        completedToday: 0,
        dailyGoal: 20,
        streak: 0,
        upNext: [],
        isDemo: false,
        updatedAt: .distantPast
    )

    var hasSynced: Bool { updatedAt > .distantPast }

    var goalProgress: Double {
        guard dailyGoal > 0 else { return 0 }
        return min(Double(completedToday) / Double(dailyGoal), 1)
    }

    static func load() -> GRReviewSnapshot? {
        guard let data = GRShared.defaults.data(forKey: storageKey) else { return nil }
        return try? JSONDecoder().decode(GRReviewSnapshot.self, from: data)
    }

    func save() {
        guard let data = try? JSONEncoder().encode(self) else { return }
        GRShared.defaults.set(data, forKey: Self.storageKey)
    }
}

/// A link or text shared into GraphRecall from another app, ingested directly or drained on launch.
struct GRSharedImport: Codable, Identifiable, Equatable, Sendable {
    enum Kind: String, Codable, Sendable {
        case url
        case text
    }

    enum Status: String, Codable, Sendable {
        case pending
        case uploading
        case sent
        case failed
    }

    var id: UUID
    var kind: Kind
    var content: String
    var title: String?
    var createdAt: Date
    var status: Status
    var lastError: String?
    var warnings: [String]
    var noteId: String?

    init(
        kind: Kind,
        content: String,
        title: String? = nil,
        status: Status = .pending,
        lastError: String? = nil,
        warnings: [String] = [],
        noteId: String? = nil
    ) {
        self.id = UUID()
        self.kind = kind
        self.content = content
        self.title = title
        self.createdAt = .now
        self.status = status
        self.lastError = lastError
        self.warnings = warnings
        self.noteId = noteId
    }

    private enum CodingKeys: String, CodingKey {
        case id, kind, content, title, createdAt, status, lastError, warnings, noteId
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        kind = try c.decode(Kind.self, forKey: .kind)
        content = try c.decode(String.self, forKey: .content)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        createdAt = try c.decodeIfPresent(Date.self, forKey: .createdAt) ?? .now
        status = try c.decodeIfPresent(Status.self, forKey: .status) ?? .pending
        lastError = try c.decodeIfPresent(String.self, forKey: .lastError)
        warnings = try c.decodeIfPresent([String].self, forKey: .warnings) ?? []
        noteId = try c.decodeIfPresent(String.self, forKey: .noteId)
    }

    var displayTitle: String {
        if let title, !title.isEmpty { return title }
        if kind == .url, let url = URL(string: content), let host = url.host { return host }
        return String(content.prefix(60))
    }
}

enum GRShareInbox {
    static let storageKey = "share.inbox"

    static func load() -> [GRSharedImport] {
        guard let data = GRShared.defaults.data(forKey: storageKey) else { return [] }
        return (try? JSONDecoder().decode([GRSharedImport].self, from: data)) ?? []
    }

    static func append(_ item: GRSharedImport) {
        var items = load()
        items.insert(item, at: 0)
        save(Array(items.prefix(20)))
    }

    static func update(
        id: UUID,
        status: GRSharedImport.Status,
        error: String? = nil,
        warnings: [String]? = nil,
        noteId: String? = nil
    ) {
        var items = load()
        guard let idx = items.firstIndex(where: { $0.id == id }) else { return }
        items[idx].status = status
        items[idx].lastError = error
        if let warnings { items[idx].warnings = warnings }
        if let noteId { items[idx].noteId = noteId }
        save(items)
    }

    static func pendingOrFailed(staleUploadSeconds: TimeInterval = 90) -> [GRSharedImport] {
        let cutoff = Date().addingTimeInterval(-staleUploadSeconds)
        return load().filter { item in
            switch item.status {
            case .pending, .failed:
                return true
            case .uploading:
                return item.createdAt < cutoff
            case .sent:
                return false
            }
        }
    }

    static func remove(id: UUID) {
        GRShareUploadConfig.removePayloadFile(for: id)
        save(load().filter { $0.id != id })
    }

    static func clear() {
        for item in load() {
            GRShareUploadConfig.removePayloadFile(for: item.id)
        }
        GRShared.defaults.removeObject(forKey: storageKey)
    }

    private static func save(_ items: [GRSharedImport]) {
        guard let data = try? JSONEncoder().encode(items) else { return }
        GRShared.defaults.set(data, forKey: storageKey)
    }
}
