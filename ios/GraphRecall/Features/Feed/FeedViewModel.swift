import Foundation
import Observation

@MainActor
@Observable
final class FeedViewModel {
    var items: [FeedItem] = []
    var stats: UserStats?
    var dueTotal: Int = 0
    var streak: Int = 0
    var completedToday: Int = 0
    var dailyGoal: Int = 20
    var isLoading = false
    var isOffline = false
    var pendingFlushCount = 0
    var errorMessage: String?
    var revealedIds: Set<String> = []
    var currentIndex: Int = 0
    var dumpBannerCount: Int = 0

    var currentItem: FeedItem? {
        guard items.indices.contains(currentIndex) else { return nil }
        return items[currentIndex]
    }

    var progressLabel: String {
        "\(completedToday)/\(dailyGoal)"
    }

    func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        await flushOfflineQueue()

        let dumpItems = await OfflineReviewStore.shared.loadDumpItems()
        dumpBannerCount = dumpItems.count

        do {
            let feed = try await APIClient.shared.fetchFeed()
            let userStats = try? await APIClient.shared.fetchStats()
            let due = try? await APIClient.shared.dueCount()

            items = Self.merge(server: feed.items, dump: dumpItems)
            completedToday = feed.completedToday
            dailyGoal = feed.dailyGoal
            streak = feed.streakDays
            dueTotal = max(due?.total ?? feed.totalDueToday, items.count)
            stats = userStats
            isOffline = false
            currentIndex = 0
            revealedIds.removeAll()

            await OfflineReviewStore.shared.cacheFeed(feed)
            // Drop dump-local cards that already arrived from server
            let serverIds = Set(feed.items.map(\.id))
            await OfflineReviewStore.shared.clearDumpItems(ids: serverIds)
            dumpBannerCount = await OfflineReviewStore.shared.loadDumpItems().count
            pendingFlushCount = await OfflineReviewStore.shared.load().count
        } catch {
            isOffline = true
            errorMessage = APIError.userFacing(error, resource: "feed")
            if let cached = await OfflineReviewStore.shared.cachedFeed() {
                items = Self.merge(server: cached.items, dump: dumpItems)
                completedToday = cached.completedToday
                dailyGoal = cached.dailyGoal
                streak = cached.streakDays
                dueTotal = max(cached.totalDueToday, items.count)
            } else {
                items = dumpItems
                dueTotal = items.count
            }
            pendingFlushCount = await OfflineReviewStore.shared.load().count
            currentIndex = 0
        }
    }

    private static func merge(server: [FeedItem], dump: [FeedItem]) -> [FeedItem] {
        let serverIds = Set(server.map(\.id))
        let pending = dump.filter { !serverIds.contains($0.id) }
        return pending + server
    }

    func reveal(_ id: String) {
        revealedIds.insert(id)
    }

    func grade(_ difficulty: ReviewDifficulty) async {
        guard let item = currentItem else { return }
        let itemType = item.itemType.rawValue
        let gradedId = item.id

        do {
            if isOffline {
                throw APIError.transport(URLError(.notConnectedToInternet))
            }
            _ = try await APIClient.shared.submitReview(
                itemId: item.id,
                itemType: itemType,
                difficulty: difficulty
            )
            completedToday += 1
            await OfflineReviewStore.shared.clearDumpItems(ids: [gradedId])
            dumpBannerCount = await OfflineReviewStore.shared.loadDumpItems().count
            advance()
        } catch {
            let pending = PendingOfflineReview(
                itemId: item.id,
                itemType: itemType,
                difficulty: difficulty,
                queuedAt: Date()
            )
            await OfflineReviewStore.shared.enqueue(pending)
            await OfflineReviewStore.shared.clearDumpItems(ids: [gradedId])
            pendingFlushCount = await OfflineReviewStore.shared.load().count
            dumpBannerCount = await OfflineReviewStore.shared.loadDumpItems().count
            isOffline = true
            completedToday += 1
            advance()
        }
    }

    private func advance() {
        if let item = currentItem {
            revealedIds.remove(item.id)
        }
        if currentIndex + 1 < items.count {
            currentIndex += 1
        } else {
            currentIndex = items.count
        }
    }

    func flushOfflineQueue() async {
        let pending = await OfflineReviewStore.shared.load()
        guard !pending.isEmpty else { return }

        var remaining: [PendingOfflineReview] = []
        for review in pending {
            do {
                _ = try await APIClient.shared.submitReview(
                    itemId: review.itemId,
                    itemType: review.itemType,
                    difficulty: review.difficulty
                )
            } catch {
                remaining.append(review)
            }
        }
        await OfflineReviewStore.shared.replaceAll(remaining)
        pendingFlushCount = remaining.count
        if remaining.isEmpty {
            isOffline = false
        }
    }
}
