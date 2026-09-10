import Foundation

/// Queues SM-2 reviews when offline and flushes when connectivity returns.
actor OfflineReviewStore {
    static let shared = OfflineReviewStore()
    private let key = "gr.offline.reviews"
    private let feedKey = "gr.offline.feed"
    private let defaults = UserDefaults.standard

    private func makeEncoder() -> JSONEncoder {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }

    private func makeDecoder() -> JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }

    func load() -> [PendingOfflineReview] {
        guard let data = defaults.data(forKey: key) else { return [] }
        return (try? makeDecoder().decode([PendingOfflineReview].self, from: data)) ?? []
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
    }

    private func save(_ reviews: [PendingOfflineReview]) {
        if let data = try? makeEncoder().encode(reviews) {
            defaults.set(data, forKey: key)
        }
    }

    /// Persist a lightweight feed snapshot for offline Today.
    func cacheFeed(_ response: FeedResponse) {
        if let data = try? makeEncoder().encode(response) {
            defaults.set(data, forKey: feedKey)
        }
    }

    func cachedFeed() -> FeedResponse? {
        guard let data = defaults.data(forKey: feedKey) else { return nil }
        return try? makeDecoder().decode(FeedResponse.self, from: data)
    }

    func clearAll() {
        defaults.removeObject(forKey: key)
        defaults.removeObject(forKey: feedKey)
    }
}
