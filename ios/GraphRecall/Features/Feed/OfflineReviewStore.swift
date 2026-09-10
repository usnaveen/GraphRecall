import Foundation

/// Queues SM-2 reviews when offline and flushes when connectivity returns.
actor OfflineReviewStore {
    static let shared = OfflineReviewStore()
    private let key = "gr.offline.reviews"
    private let defaults = UserDefaults.standard

    private var isoEncoder: JSONEncoder {
        let e = isoEncoder
        e.dateEncodingStrategy = .iso8601
        return e
    }

    private var isoDecoder: JSONDecoder {
        let d = isoDecoder
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
    }

    private func save(_ reviews: [PendingOfflineReview]) {
        if let data = try? isoEncoder.encode(reviews) {
            defaults.set(data, forKey: key)
        }
    }

    /// Persist a lightweight feed snapshot for offline Today.
    func cacheFeed(_ response: FeedResponse) {
        if let data = try? isoEncoder.encode(response) {
            defaults.set(data, forKey: "gr.offline.feed")
        }
    }

    func cachedFeed() -> FeedResponse? {
        guard let data = defaults.data(forKey: "gr.offline.feed") else { return nil }
        return try? isoDecoder.decode(FeedResponse.self, from: data)
    }
}
