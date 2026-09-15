import Foundation
import Observation
import WidgetKit

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
    /// What the feed actually shows: everything due, then concepts worth revisiting, extended as
    /// you scroll so the feed never dead-ends.
    var queue: [FeedItem] = []
    /// Grade recorded per card in this session (the difficulty slider's result).
    var grades: [String: ReviewDifficulty] = [:]
    var gradedIds: Set<String> = []
    /// Concepts from the graph, coldest first, used to pad the feed past the due cards.
    @ObservationIgnored private var revisitPool: [FeedItem] = []
    @ObservationIgnored private var revisitCursor = 0
    /// NAV-34 — optimistic like / save chrome (web likedItems / savedItems parity).
    var likedIds: Set<String> = []
    var savedIds: Set<String> = []
    var softBanner: String?
    /// Domains reported by `/api/feed` — drive the Today focus-session chips.
    var domains: [String] = []
    /// When set, review sessions and Up Next only include this domain.
    var focusDomain: String?
    /// Cards graded since the last load — keeps the widget's due count honest between reloads.
    private var gradedSinceLoad = 0
    @ObservationIgnored private var softBannerTask: Task<Void, Never>?

    /// Settings → Daily goal. 0 means "use the server's goal".
    static var dailyGoalOverride: Int? {
        let value = UserDefaults.standard.integer(forKey: GRSettingsKey.dailyGoal)
        return value > 0 ? value : nil
    }

    var currentItem: FeedItem? {
        guard items.indices.contains(currentIndex) else { return nil }
        return items[currentIndex]
    }

    var progressLabel: String {
        "\(completedToday)/\(dailyGoal)"
    }

    var sessionQueue: [FeedItem] {
        guard let focusDomain else { return items }
        return items.filter { $0.domain == focusDomain }
    }

    var upNext: [FeedItem] { Array(sessionQueue.prefix(4)) }

    var remainingToGoal: Int { max(dailyGoal - completedToday, 0) }

    var goalProgress: Double {
        guard dailyGoal > 0 else { return 0 }
        return min(Double(completedToday) / Double(dailyGoal), 1)
    }

    var retentionLabel: String {
        guard let rate = stats?.accuracyRate, rate > 0 else { return "—" }
        let pct = rate <= 1 ? rate * 100 : rate
        return "\(Int(pct.rounded()))%"
    }

    var focusDomains: [(name: String, count: Int)] {
        let names = domains.isEmpty ? Array(Set(items.compactMap(\.domain))) : domains
        return names
            .compactMap { name -> (name: String, count: Int)? in
                let count = items.filter { $0.domain == name }.count
                return count > 0 ? (name, count) : nil
            }
            .sorted { $0.count > $1.count }
    }

    func load() async {
        isLoading = true
        errorMessage = nil
        gradedSinceLoad = 0
        defer {
            isLoading = false
            if let override = Self.dailyGoalOverride { dailyGoal = override }
            publishWidgetSnapshot()
        }

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
                domains = feed.domains
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
            rebuildQueue()
            resetCardState()
        } catch {
            isOffline = true
            errorMessage = APIError.userFacing(error, resource: "feed")
            if let cached = await OfflineReviewStore.shared.cachedFeed(), !cached.items.isEmpty {
                items = Self.merge(server: cached.items, dump: dumpItems)
                completedToday = cached.completedToday
                dailyGoal = cached.dailyGoal
                streak = cached.streakDays
                domains = cached.domains
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
            rebuildQueue()
            resetCardState()
        }
    }

    /// Due cards first, then whatever revisit cards were already prepared.
    private func rebuildQueue() {
        revisitCursor = 0
        queue = items
        grades = [:]
        gradedIds = []
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
        await submitGrade(for: item, difficulty: difficulty)
        advance()
    }

    // MARK: - Feed queue

    func isRevisit(_ item: FeedItem) -> Bool {
        item.id.hasPrefix("revisit-")
    }

    /// Records the difficulty-slider grade for a specific card without moving the feed.
    func grade(_ item: FeedItem, difficulty: ReviewDifficulty) async {
        grades[item.id] = difficulty
        gradedIds.insert(item.id)
        // Revisit cards are local reminders, not scheduled reviews.
        guard !isRevisit(item) else { return }
        await submitGrade(for: item, difficulty: difficulty)
    }

    /// Concepts that aren't due but have gone cold — the "more for you" part of the feed.
    func loadRevisitPool() async {
        guard revisitPool.isEmpty else { return }
        do {
            let graph = try await APIClient.shared.fetchGraph(limit: 300)
            let dueConcepts = Set(items.compactMap(\.conceptId))
            revisitPool = graph.nodes
                .filter { !dueConcepts.contains($0.id) }
                .sorted { ($0.masteryLevel ?? 0) < ($1.masteryLevel ?? 0) }
                .prefix(60)
                .map { node in
                    var content: [String: AnyCodable] = ["title": AnyCodable(node.name)]
                    if let definition = node.definition, !definition.isEmpty {
                        content["definition"] = AnyCodable(definition)
                    }
                    if let domain = node.domain, !domain.isEmpty {
                        content["tagline"] = AnyCodable(domain)
                    }
                    return FeedItem(
                        id: "revisit-\(node.id)",
                        itemType: .showcase,
                        content: content,
                        conceptId: node.id,
                        conceptName: node.name,
                        domain: node.domain
                    )
                }
            if queue.isEmpty { await extendQueueIfNeeded(currentIndex: 0) }
        } catch {
            // No graph yet: the feed just ends after the due cards.
            revisitPool = []
        }
    }

    /// Appends more cards as the reader approaches the end; cycles the revisit pool after that.
    func extendQueueIfNeeded(currentIndex index: Int) async {
        guard index >= queue.count - 3 else { return }
        if revisitPool.isEmpty {
            await loadRevisitPool()
            guard !revisitPool.isEmpty else { return }
        }
        let cycle = revisitCursor / revisitPool.count
        let batch = (0..<min(8, revisitPool.count)).map { offset -> FeedItem in
            let base = revisitPool[(revisitCursor + offset) % revisitPool.count]
            guard cycle > 0 else { return base }
            // Same concept, fresh identity, so a second pass can appear further down.
            return FeedItem(
                id: "\(base.id)-\(cycle)",
                itemType: base.itemType,
                content: base.content,
                conceptId: base.conceptId,
                conceptName: base.conceptName,
                domain: base.domain
            )
        }
        revisitCursor += batch.count
        queue.append(contentsOf: batch)
    }

    /// Records a grade (API, falling back to the offline queue). Returns the server's
    /// SM-2 result when the review reached the backend.
    @discardableResult
    func submitGrade(for item: FeedItem, difficulty: ReviewDifficulty, responseTimeMs: Int? = nil) async -> ReviewSubmitResult? {
        let itemType = item.itemType.rawValue
        gradedSinceLoad += 1
        defer { publishWidgetSnapshot() }

        // Demo cards are local-only — never hit the API / offline queue.
        if item.isDemo || isDemoMode {
            completedToday += 1
            return nil
        }

        do {
            if isOffline {
                throw APIError.transport(URLError(.notConnectedToInternet))
            }
            let result = try await APIClient.shared.submitReview(
                itemId: item.id,
                itemType: itemType,
                difficulty: difficulty,
                responseTimeMs: responseTimeMs
            )
            completedToday += 1
            await OfflineReviewStore.shared.clearDumpItems(ids: [item.id])
            dumpBannerCount = await OfflineReviewStore.shared.loadDumpItems().count
            return result
        } catch {
            let pending = PendingOfflineReview(
                itemId: item.id,
                itemType: itemType,
                difficulty: difficulty,
                queuedAt: Date()
            )
            await OfflineReviewStore.shared.enqueue(pending)
            await OfflineReviewStore.shared.clearDumpItems(ids: [item.id])
            pendingFlushCount = await OfflineReviewStore.shared.load().count
            dumpBannerCount = await OfflineReviewStore.shared.loadDumpItems().count
            isOffline = true
            completedToday += 1
            return nil
        }
    }

    /// Mirrors Today into the App Group so the home-screen widget stays current.
    private func publishWidgetSnapshot() {
        let upNext = items
            .dropFirst(gradedSinceLoad)
            .prefix(3)
            .map { item in
                let name = item.conceptName?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                return name.isEmpty ? String(item.prompt.prefix(40)) : name
            }
        let snapshot = GRReviewSnapshot(
            dueCount: max(dueTotal - gradedSinceLoad, 0),
            completedToday: completedToday,
            dailyGoal: dailyGoal,
            streak: streak,
            upNext: Array(upNext),
            isDemo: isDemoMode,
            updatedAt: .now
        )
        guard snapshot != GRReviewSnapshot.load().map({ var s = $0; s.updatedAt = snapshot.updatedAt; return s }) else { return }
        snapshot.save()
        WidgetCenter.shared.reloadAllTimelines()
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
