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

        do {
            let feed = try await APIClient.shared.fetchFeed()
            let userStats = try? await APIClient.shared.fetchStats()
            let due = try? await APIClient.shared.dueCount()

            items = feed.items
            completedToday = feed.completedToday
            dailyGoal = feed.dailyGoal
            streak = feed.streakDays
            dueTotal = due?.total ?? feed.totalDueToday
            stats = userStats
            isOffline = false
            currentIndex = 0
            revealedIds.removeAll()

            await OfflineReviewStore.shared.cacheFeed(feed)
            pendingFlushCount = await OfflineReviewStore.shared.load().count
        } catch {
            isOffline = true
            errorMessage = error.localizedDescription
            if let cached = await OfflineReviewStore.shared.cachedFeed() {
                items = cached.items
                completedToday = cached.completedToday
                dailyGoal = cached.dailyGoal
                streak = cached.streakDays
                dueTotal = cached.totalDueToday
            }
            pendingFlushCount = await OfflineReviewStore.shared.load().count
        }
    }

    func reveal(_ id: String) {
        revealedIds.insert(id)
    }

    func grade(_ difficulty: ReviewDifficulty) async {
        guard let item = currentItem else { return }
        let itemType = item.itemType.rawValue

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
            advance()
        } catch {
            let pending = PendingOfflineReview(
                itemId: item.id,
                itemType: itemType,
                difficulty: difficulty,
                queuedAt: Date()
            )
            await OfflineReviewStore.shared.enqueue(pending)
            pendingFlushCount = await OfflineReviewStore.shared.load().count
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
        var pending = await OfflineReviewStore.shared.load()
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
