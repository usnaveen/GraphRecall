import Foundation
import Security

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

    /// Resolves `<TeamID>.` from `Info.plist` (`GRAppIdentifierPrefix = $(AppIdentifierPrefix)`),
    /// returning nil for unsigned ad-hoc Simulator builds so callers can omit `kSecAttrAccessGroup`.
    static var appIdentifierPrefix: String? {
        guard let raw = Bundle.main.object(forInfoDictionaryKey: "GRAppIdentifierPrefix") as? String else {
            return nil
        }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !trimmed.contains("$(") else { return nil }
        return trimmed.hasSuffix(".") ? trimmed : "\(trimmed)."
    }
}

/// Auth/endpoint snapshot shared with `GraphRecallShare` so direct background uploads authenticate cleanly.
/// Only the short-lived `access_token` is placed in the shared Keychain group (`refresh_token` stays
/// app-only in `AppAuthKeychain` so extension processes can never race refresh rotation).
enum GRSharedAuth {
    private static let apiBaseKey = "shared.auth.apiBaseURL"
    private static let legacyTokenKey = "shared.auth.bearerToken"
    private static let service = "com.usnaveen.graphrecall.shared.auth"
    private static let account = "access_token"

    private static var sharedAccessGroup: String? {
        GRShared.appIdentifierPrefix.map { "\($0)\(GRShared.appGroup)" }
    }

    static var apiBaseURL: String? {
        GRShared.defaults.string(forKey: apiBaseKey)
    }

    static var bearerToken: String? {
        // Purge any legacy plaintext token left in App Group UserDefaults.
        GRShared.defaults.removeObject(forKey: legacyTokenKey)
        return readToken()
    }

    static func sync(apiBaseURL: String, bearerToken: String?) {
        GRShared.defaults.set(apiBaseURL, forKey: apiBaseKey)
        GRShared.defaults.removeObject(forKey: legacyTokenKey)
        if let bearerToken, !bearerToken.isEmpty {
            writeToken(bearerToken)
        } else {
            deleteToken()
        }
    }

    static func clear() {
        GRShared.defaults.removeObject(forKey: apiBaseKey)
        GRShared.defaults.removeObject(forKey: legacyTokenKey)
        deleteToken()
    }

    private static func baseQuery(withAccessGroup: Bool) -> [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        if withAccessGroup, let group = sharedAccessGroup {
            query[kSecAttrAccessGroup as String] = group
        }
        return query
    }

    private static func readToken() -> String? {
        if sharedAccessGroup != nil {
            let result = copyMatching(query: baseQuery(withAccessGroup: true))
            if result.status == errSecSuccess {
                return result.token
            }
            if result.status != errSecMissingEntitlement {
                return nil
            }
        }
        let fallback = copyMatching(query: baseQuery(withAccessGroup: false))
        return fallback.status == errSecSuccess ? fallback.token : nil
    }

    private static func copyMatching(query: [String: Any]) -> (status: OSStatus, token: String?) {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &item)
        guard status == errSecSuccess,
              let data = item as? Data,
              let token = String(data: data, encoding: .utf8),
              !token.isEmpty else {
            return (status, nil)
        }
        return (status, token)
    }

    private static func writeToken(_ token: String) {
        guard let data = token.data(using: .utf8) else { return }
        if sharedAccessGroup != nil {
            let status = upsertToken(data: data, withAccessGroup: true)
            if status != errSecMissingEntitlement {
                return
            }
        }
        _ = upsertToken(data: data, withAccessGroup: false)
    }

    private static func upsertToken(data: Data, withAccessGroup: Bool) -> OSStatus {
        let query = baseQuery(withAccessGroup: withAccessGroup)
        SecItemDelete(query as CFDictionary)
        var addQuery = query
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        return SecItemAdd(addQuery as CFDictionary, nil)
    }

    private static func deleteToken() {
        if sharedAccessGroup != nil {
            SecItemDelete(baseQuery(withAccessGroup: true) as CFDictionary)
        }
        SecItemDelete(baseQuery(withAccessGroup: false) as CFDictionary)
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
    /// The server rejected it for good (e.g. a private address): don't retry it automatically on
    /// every launch. The Retry button in Create still works.
    var permanentFailure: Bool = false

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
        case id, kind, content, title, createdAt, status, lastError, warnings, noteId, permanentFailure
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
        permanentFailure = try c.decodeIfPresent(Bool.self, forKey: .permanentFailure) ?? false
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
        noteId: String? = nil,
        permanent: Bool = false
    ) {
        var items = load()
        guard let idx = items.firstIndex(where: { $0.id == id }) else { return }
        items[idx].status = status
        items[idx].lastError = error
        items[idx].permanentFailure = status == .failed && permanent
        if let warnings { items[idx].warnings = warnings }
        if let noteId { items[idx].noteId = noteId }
        save(items)
    }

    static func pendingOrFailed(staleUploadSeconds: TimeInterval = 90) -> [GRSharedImport] {
        let cutoff = Date().addingTimeInterval(-staleUploadSeconds)
        return load().filter { item in
            switch item.status {
            case .pending:
                return true
            case .failed:
                return !item.permanentFailure
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
