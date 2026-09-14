import Foundation
import Observation

struct RecentImport: Codable, Identifiable, Hashable, Sendable {
    var id = UUID()
    let title: String
    let kind: String
    var status: String
    var detail: String
    var createdAt = Date()
    var sessionId: String?
}

/// Last few Create submissions (local), so users can see what landed and reopen pending reviews.
@MainActor
@Observable
final class RecentImportsStore {
    static let shared = RecentImportsStore()

    private(set) var items: [RecentImport] = []
    @ObservationIgnored private let key = "graphrecall.recentImports"

    init() {
        if let data = UserDefaults.standard.data(forKey: key),
           let decoded = try? JSONDecoder().decode([RecentImport].self, from: data) {
            items = decoded
        }
    }

    func add(_ item: RecentImport) {
        if let sessionId = item.sessionId {
            items.removeAll { $0.sessionId == sessionId }
        }
        items.insert(item, at: 0)
        items = Array(items.prefix(15))
        save()
    }

    func markReviewed(sessionId: String, status: String, detail: String) {
        guard let idx = items.firstIndex(where: { $0.sessionId == sessionId }) else { return }
        items[idx].status = status
        items[idx].detail = detail
        save()
    }

    func clear() {
        items = []
        save()
    }

    private func save() {
        if let data = try? JSONEncoder().encode(items) {
            UserDefaults.standard.set(data, forKey: key)
        }
    }
}
