import Foundation

/// State shared between the app, the Today widget and the share extension through the App Group.
enum GRShared {
    static let appGroup = "group.com.usnaveen.graphrecall"
    static let urlScheme = "graphrecall"

    static var defaults: UserDefaults {
        UserDefaults(suiteName: appGroup) ?? .standard
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

/// A link or text shared into GraphRecall from another app, waiting in Create.
struct GRSharedImport: Codable, Identifiable, Equatable, Sendable {
    enum Kind: String, Codable, Sendable {
        case url
        case text
    }

    var id: UUID
    var kind: Kind
    var content: String
    var title: String?
    var createdAt: Date

    init(kind: Kind, content: String, title: String? = nil) {
        id = UUID()
        self.kind = kind
        self.content = content
        self.title = title
        createdAt = .now
    }

    var displayTitle: String {
        if let title, !title.isEmpty { return title }
        if kind == .url, let host = URL(string: content)?.host() { return host }
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

    static func remove(id: UUID) {
        save(load().filter { $0.id != id })
    }

    private static func save(_ items: [GRSharedImport]) {
        guard let data = try? JSONEncoder().encode(items) else { return }
        GRShared.defaults.set(data, forKey: storageKey)
    }
}
