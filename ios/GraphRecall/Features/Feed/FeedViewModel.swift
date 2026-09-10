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
    var isDemoMode = false
    var pendingFlushCount = 0
    var errorMessage: String?
    var revealedIds: Set<String> = []
    var selectedOptionIds: [String: String] = [:]
    var fillAnswers: [String: String] = [:]
    var hintIds: Set<String> = []
    var currentIndex: Int = 0
    var dumpBannerCount: Int = 0
    /// NAV-34 — optimistic like / save chrome (web likedItems / savedItems parity).
    var likedIds: Set<String> = []
    var savedIds: Set<String> = []
    var softBanner: String?
    @ObservationIgnored private var softBannerTask: Task<Void, Never>?

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

            let merged = Self.merge(server: feed.items, dump: dumpItems)
            isDemoMode = false

            // NAV-24: empty live feed → seed rich demo cards (never blank Simulator).
            if merged.isEmpty {
                isOffline = false
                applyDemoSeed(reason: "Feed returned no cards — showing Demo pack.")
            } else {
                items = merged
                completedToday = feed.completedToday
                dailyGoal = feed.dailyGoal
                streak = feed.streakDays
                dueTotal = max(due?.total ?? feed.totalDueToday, items.count)
                stats = userStats
                isOffline = false
                await OfflineReviewStore.shared.cacheFeed(feed)
            }

            let serverIds = Set(feed.items.map(\.id))
            await OfflineReviewStore.shared.clearDumpItems(ids: serverIds)
            dumpBannerCount = await OfflineReviewStore.shared.loadDumpItems().count
            pendingFlushCount = await OfflineReviewStore.shared.load().count
            currentIndex = 0
            resetCardState()
        } catch {
            isOffline = true
            errorMessage = APIError.userFacing(error, resource: "feed")
            if let cached = await OfflineReviewStore.shared.cachedFeed(), !cached.items.isEmpty {
                items = Self.merge(server: cached.items, dump: dumpItems)
                completedToday = cached.completedToday
                dailyGoal = cached.dailyGoal
                streak = cached.streakDays
                dueTotal = max(cached.totalDueToday, items.count)
                isDemoMode = items.contains(where: \.isDemo)
            } else if !dumpItems.isEmpty {
                items = dumpItems
                dueTotal = items.count
                isDemoMode = false
            } else {
                // NAV-24: 404 / offline with no cache → demo pack
                applyDemoSeed(reason: errorMessage ?? "Couldn't reach feed — showing Demo pack.")
            }
            pendingFlushCount = await OfflineReviewStore.shared.load().count
            currentIndex = 0
            resetCardState()
        }
    }

    private func applyDemoSeed(reason: String) {
        let demo = DemoFeedSeed.response
        items = demo.items
        completedToday = demo.completedToday
        dailyGoal = demo.dailyGoal
        streak = demo.streakDays
        dueTotal = demo.totalDueToday
        isDemoMode = true
        errorMessage = reason
        Task {
            await OfflineReviewStore.shared.cacheFeed(demo)
        }
    }

    private func resetCardState() {
        revealedIds.removeAll()
        selectedOptionIds.removeAll()
        fillAnswers.removeAll()
        hintIds.removeAll()
    }

    private static func merge(server: [FeedItem], dump: [FeedItem]) -> [FeedItem] {
        let serverIds = Set(server.map(\.id))
        let pending = dump.filter { !serverIds.contains($0.id) }
        return pending + server
    }

    func reveal(_ id: String) {
        revealedIds.insert(id)
    }

    func selectOption(itemId: String, optionId: String) {
        selectedOptionIds[itemId] = optionId
    }

    func setFillAnswer(itemId: String, text: String) {
        fillAnswers[itemId] = text
    }

    func toggleHint(_ id: String) {
        if hintIds.contains(id) {
            hintIds.remove(id)
        } else {
            hintIds.insert(id)
        }
    }

    func grade(_ difficulty: ReviewDifficulty) async {
        guard let item = currentItem else { return }
        let itemType = item.itemType.rawValue
        let gradedId = item.id

        // Demo cards are local-only — never hit the API / offline queue.
        if item.isDemo || isDemoMode {
            completedToday += 1
            advance()
            return
        }

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
            selectedOptionIds.removeValue(forKey: item.id)
            fillAnswers.removeValue(forKey: item.id)
            hintIds.remove(item.id)
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

    // MARK: - NAV-34 Like / Save / soft banner

    func showSoftBanner(_ message: String) {
        softBanner = message
        softBannerTask?.cancel()
        softBannerTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 2_400_000_000)
            guard !Task.isCancelled else { return }
            softBanner = nil
        }
    }

    func dismissSoftBanner() {
        softBannerTask?.cancel()
        softBanner = nil
    }

    func toggleLike(for item: FeedItem? = nil) async {
        guard let item = item ?? currentItem else { return }
        let wasLiked = likedIds.contains(item.id)
        if wasLiked { likedIds.remove(item.id) } else { likedIds.insert(item.id) }

        // Demo / demo-mode: local-only — never POST.
        if item.isDemo || isDemoMode {
            showSoftBanner(wasLiked ? "Unliked (demo)" : "Liked (demo)")
            return
        }

        guard let apiType = item.likeSaveAPIItemType else {
            // Unsupported type: keep local optimistic state.
            showSoftBanner(wasLiked ? "Unliked" : "Liked")
            return
        }

        if isOffline {
            // Soft-disable: revert optimistic flip.
            if wasLiked { likedIds.insert(item.id) } else { likedIds.remove(item.id) }
            showSoftBanner("Can\u{2019}t like while offline")
            return
        }

        do {
            let result = try await APIClient.shared.likeFeedItem(id: item.id, itemType: apiType)
            if result.isLiked {
                likedIds.insert(item.id)
            } else {
                likedIds.remove(item.id)
            }
            showSoftBanner(result.isLiked ? "Liked" : "Unliked")
        } catch {
            if wasLiked { likedIds.insert(item.id) } else { likedIds.remove(item.id) }
            showSoftBanner(APIError.userFacing(error, resource: "like"))
        }
    }

    func toggleSave(for item: FeedItem? = nil) async {
        guard let item = item ?? currentItem else { return }
        let wasSaved = savedIds.contains(item.id)
        if wasSaved { savedIds.remove(item.id) } else { savedIds.insert(item.id) }

        if item.isDemo || isDemoMode {
            showSoftBanner(wasSaved ? "Removed save (demo)" : "Saved (demo)")
            return
        }

        guard let apiType = item.likeSaveAPIItemType else {
            showSoftBanner(wasSaved ? "Removed save" : "Saved")
            return
        }

        if isOffline {
            if wasSaved { savedIds.insert(item.id) } else { savedIds.remove(item.id) }
            showSoftBanner("Can\u{2019}t save while offline")
            return
        }

        do {
            let result = try await APIClient.shared.saveFeedItem(id: item.id, itemType: apiType)
            if result.isSaved {
                savedIds.insert(item.id)
            } else {
                savedIds.remove(item.id)
            }
            showSoftBanner(result.isSaved ? "Saved" : "Removed save")
        } catch {
            if wasSaved { savedIds.insert(item.id) } else { savedIds.remove(item.id) }
            showSoftBanner(APIError.userFacing(error, resource: "save"))
        }
    }

}
