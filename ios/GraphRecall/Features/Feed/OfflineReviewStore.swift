import Foundation

extension Notification.Name {
    static let grDumpCompleted = Notification.Name("gr.dump.completed")
    static let grFeedShouldReload = Notification.Name("gr.feed.shouldReload")
}

/// Queues SM-2 reviews when offline and caches dump teach cards for Today.
actor OfflineReviewStore {
    static let shared = OfflineReviewStore()
    private let key = "gr.offline.reviews"
    private let feedKey = "gr.offline.feed"
    private let dumpKey = "gr.offline.dumpCards"
    private let defaults = UserDefaults.standard

    private var isoEncoder: JSONEncoder {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }

    private var isoDecoder: JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }

    func load() -> [PendingOfflineReview] {
        guard let data = defaults.data(forKey: key) else { return [] }
        return (try? isoDecoder.decode([PendingOfflineReview].self, from: data)) ?? []
    }

    func enqueue(_ review: PendingOfflineReview) {
        var all = load()
        all.append(review)
        save(all)
    }

    func replaceAll(_ reviews: [PendingOfflineReview]) {
        save(reviews)
    }

    func clear() {
        defaults.removeObject(forKey: key)
        defaults.removeObject(forKey: feedKey)
        defaults.removeObject(forKey: dumpKey)
    }

    func clearAll() {
        clear()
    }

    private func save(_ reviews: [PendingOfflineReview]) {
        if let data = try? isoEncoder.encode(reviews) {
            defaults.set(data, forKey: key)
        }
    }

    func cacheFeed(_ response: FeedResponse) {
        if let data = try? isoEncoder.encode(response) {
            defaults.set(data, forKey: feedKey)
        }
    }

    func cachedFeed() -> FeedResponse? {
        guard let data = defaults.data(forKey: feedKey) else { return nil }
        return try? isoDecoder.decode(FeedResponse.self, from: data)
    }

    /// Persist teach cards from Concept Dump so Feed can surface them immediately.
    func ingestDump(_ response: ConceptDumpResponse) {
        var items = loadDumpItems()
        let existing = Set(items.map(\.id))
        for result in response.results where result.status == "ok" {
            for card in result.cards {
                if existing.contains(card.id) { continue }
                let type = FeedItemType.parse(card.type)
                var content: [String: AnyCodable] = [:]
                if let front = card.front { content["front"] = AnyCodable(front) }
                if let back = card.back { content["back"] = AnyCodable(back) }
                if !result.sources.isEmpty {
                    content["sources"] = AnyCodable(result.sources.map { ["title": $0.title, "url": $0.url] })
                }
                let item = FeedItem(
                    id: card.id,
                    itemType: type,
                    content: content,
                    conceptId: result.conceptId,
                    conceptName: result.concept,
                    domain: "concept_dump",
                    priorityScore: 1.0,
                    dueDate: Date()
                )
                items.insert(item, at: 0)
            }
        }
        if let data = try? isoEncoder.encode(items) {
            defaults.set(data, forKey: dumpKey)
        }
    }

    func loadDumpItems() -> [FeedItem] {
        guard let data = defaults.data(forKey: dumpKey) else { return [] }
        return (try? isoDecoder.decode([FeedItem].self, from: data)) ?? []
    }

    func clearDumpItems(ids: Set<String>) {
        let kept = loadDumpItems().filter { !ids.contains($0.id) }
        if let data = try? isoEncoder.encode(kept) {
            defaults.set(data, forKey: dumpKey)
        }
    }
}
