import SwiftUI

enum ProfileNavRoute: Hashable {
    case library
    case notes
    case concepts
    case uploads
    case quizzes
    case saved
}

struct ProfileView: View {
    var openLibraryToken: Int = 0

    @AppStorage(GRSettingsKey.displayName) private var displayName = ""
    @Environment(AppRouter.self) private var router
    @State private var showSettings = false
    @State private var tokenPresent = false
    @State private var stats: UserStats?
    @State private var statsError: String?
    @State private var isLoadingStats = false
    @State private var schedule: [ScheduleDay] = []
    @State private var scheduleError: String?
    @State private var notesCount = 0
    @State private var conceptsCount = 0
    @State private var uploadsCount = 0
    @State private var quizCount = 0
    @State private var booksCount = 0
    @State private var savedCount = 0
    @State private var domainMastery: [DomainMastery] = []
    @State private var path = NavigationPath()

    struct DomainMastery: Identifiable {
        let domain: String
        let mastery: Double
        let count: Int
        var id: String { domain }
    }

    struct WeekDay: Identifiable {
        let id: String
        let label: String
        let reviews: Int
        let accuracy: Double?
        let concepts: Int
        let isToday: Bool
    }

    var body: some View {
        NavigationStack(path: $path) {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                GRBackdropGlow(offset: CGSize(width: -110, height: -240))

                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        header

                        Group {
                            identityCard
                            todayCard
                            dueChips
                            weeklyInsights
                            if !domainMastery.isEmpty { masteryCard }
                            activitySection
                            VStack(alignment: .leading, spacing: 10) {
                                GRSectionHeader(title: "Upcoming reviews")
                                CalendarScheduleView(schedule: schedule)
                                if let scheduleError {
                                    Text(scheduleError)
                                        .font(GRType.caption)
                                        .foregroundStyle(GRColor.warning)
                                }
                            }
                            libraryGrid
                        }
                        .padding(.horizontal, 20)
                    }
                }
                .refreshable { await refresh() }
            }
            .navigationDestination(for: ProfileNavRoute.self) { route in
                switch route {
                case .library: LibraryView()
                case .notes: ProfileNotesListView()
                case .concepts: ProfileConceptsListView()
                case .uploads: ProfileUploadsListView()
                case .quizzes: ProfileQuizzesListView()
                case .saved: SavedItemsListView()
                }
            }
            .navigationBarHidden(true)
        }
        .task { await refresh() }
        .onChange(of: openLibraryToken) { _, newValue in
            guard newValue > 0 else { return }
            path.append(ProfileNavRoute.library)
        }
        .sheet(isPresented: $showSettings, onDismiss: { Task { await refresh() } }) {
            SettingsView()
                .presentationDragIndicator(.visible)
        }
    }

    // MARK: - Header / identity

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            GRScreenHeader(title: "Profile", subtitle: "Your learning at a glance")
            GRIconButton(systemImage: "gearshape.fill", tint: GRColor.textPrimary, accessibilityLabel: "Settings") {
                showSettings = true
            }
            .padding(.trailing, 20)
            .padding(.top, 14)
        }
    }

    private var identityName: String {
        if !displayName.trimmingCharacters(in: .whitespaces).isEmpty { return displayName }
        return tokenPresent ? "Signed in" : "Guest"
    }

    private var identityCard: some View {
        GlassCard {
            HStack(spacing: 14) {
                ZStack {
                    Circle()
                        .fill(LinearGradient(colors: [GRColor.accent, GRColor.accentCyan], startPoint: .topLeading, endPoint: .bottomTrailing))
                        .frame(width: 64, height: 64)
                    Circle()
                        .fill(GRColor.canvas)
                        .frame(width: 58, height: 58)
                    Text(String(identityName.prefix(1)).uppercased())
                        .font(GRType.title)
                        .foregroundStyle(GRColor.textPrimary)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(identityName)
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Text(tokenPresent ? "Session active · reviews sync" : "Not signed in · open Settings to sign in")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                    HStack(spacing: 6) {
                        if let streak = stats?.streakDays, streak > 0 {
                            GRChip(title: "\(streak)d streak", systemImage: "flame.fill", style: .tinted(.accent), compact: true)
                        }
                        if let total = stats?.totalReviews, total > 0 {
                            GRChip(title: "\(total) reviews", systemImage: "checkmark.seal.fill", compact: true)
                        }
                    }
                    .padding(.top, 2)
                }
                Spacer(minLength: 0)
                GRIconButton(systemImage: "pencil", style: .plain, accessibilityLabel: "Edit profile") {
                    showSettings = true
                }
            }
        }
    }

    // MARK: - Today (moved off the feed, which is now content-only)

    private var goalTarget: Int {
        FeedViewModel.dailyGoalOverride ?? stats?.dailyGoal ?? 20
    }

    private var completedToday: Int { stats?.completedToday ?? 0 }

    private var goalProgress: Double {
        guard goalTarget > 0 else { return 0 }
        return min(Double(completedToday) / Double(goalTarget), 1)
    }

    private var todayCard: some View {
        GlassCard(cornerRadius: 22) {
            HStack(spacing: 18) {
                GRProgressRing(progress: goalProgress, lineWidth: 9) {
                    VStack(spacing: 0) {
                        Text("\(completedToday)/\(goalTarget)")
                            .font(GRType.title)
                            .foregroundStyle(GRColor.textPrimary)
                            .minimumScaleFactor(0.7)
                        Text("today")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                    }
                }
                .frame(width: 96, height: 96)

                VStack(alignment: .leading, spacing: 6) {
                    if let streak = stats?.streakDays, streak > 0 {
                        Label("\(streak)-day streak", systemImage: "flame.fill")
                            .font(GRType.caption.weight(.bold))
                            .foregroundStyle(GRColor.amber)
                    }
                    Text(todayTitle)
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(todaySubtitle)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                    Button {
                        router.pendingStartReview = true
                        router.select(.feed)
                    } label: {
                        Label("Start review", systemImage: "play.fill")
                    }
                    .grButton(.primary, compact: true)
                    .disabled((stats?.dueToday ?? 0) == 0)
                    .accessibilityIdentifier("today.startReview")
                    .padding(.top, 2)
                }
            }
        }
    }

    private var todayTitle: String {
        let due = stats?.dueToday ?? 0
        if due == 0 { return completedToday > 0 ? "All clear for now" : "Nothing due yet" }
        let remaining = max(goalTarget - completedToday, 0)
        return remaining == 0 ? "Goal reached — keep the streak warm" : "\(remaining) more to hit your goal"
    }

    private var todaySubtitle: String {
        let due = stats?.dueToday ?? 0
        guard due > 0 else { return "Your feed still has plenty to browse." }
        let minutes = max(1, Int((Double(due) * 20 / 60).rounded()))
        return "≈ \(minutes) min · \(due) card\(due == 1 ? "" : "s") due"
    }

    // MARK: - Due chips

    private var dueChips: some View {
        VStack(alignment: .leading, spacing: 10) {
            if isLoadingStats && stats == nil {
                ProgressView()
                    .tint(GRColor.accent)
                    .frame(maxWidth: .infinity, minHeight: 56)
            } else {
                HStack(spacing: 10) {
                    GRStatChip(title: "Due", value: "\(stats?.dueToday ?? 0)", systemImage: "tray.full.fill")
                    GRStatChip(title: "Done", value: "\(stats?.completedToday ?? 0)", systemImage: "checkmark.circle.fill")
                    GRStatChip(title: "Overdue", value: "\(stats?.overdue ?? 0)", systemImage: "exclamationmark.triangle.fill")
                }
            }
            if let statsError {
                Text(statsError)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.warning)
            }
        }
    }

    // MARK: - Weekly insights

    private var weekDays: [WeekDay] {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0) ?? .gmt
        let today = calendar.startOfDay(for: Date())
        let keyFormatter = DateFormatter()
        keyFormatter.calendar = calendar
        keyFormatter.locale = Locale(identifier: "en_US_POSIX")
        keyFormatter.timeZone = calendar.timeZone
        keyFormatter.dateFormat = "yyyy-MM-dd"
        let labelFormatter = DateFormatter()
        labelFormatter.timeZone = calendar.timeZone
        labelFormatter.dateFormat = "EEEEE"

        var byKey: [String: DailyActivity] = [:]
        for day in stats?.dailyActivity ?? [] {
            let key = day.date.split(separator: "T").first.map(String.init) ?? day.date
            byKey[key] = day
        }

        return (0..<7).reversed().compactMap { offset -> WeekDay? in
            guard let date = calendar.date(byAdding: .day, value: -offset, to: today) else { return nil }
            let key = keyFormatter.string(from: date)
            let activity = byKey[key]
            let accuracy = activity.flatMap { $0.reviewsCompleted > 0 ? ($0.accuracy > 1 ? $0.accuracy / 100 : $0.accuracy) : nil }
            return WeekDay(
                id: key,
                label: labelFormatter.string(from: date),
                reviews: activity?.reviewsCompleted ?? 0,
                accuracy: accuracy,
                concepts: activity?.conceptsLearned ?? 0,
                isToday: offset == 0
            )
        }
    }

    private var weeklyInsights: some View {
        let days = weekDays
        let reviews = days.map(\.reviews).reduce(0, +)
        let accuracies = days.compactMap(\.accuracy)
        let accuracy = accuracies.isEmpty ? nil : accuracies.reduce(0, +) / Double(accuracies.count)
        let concepts = days.map(\.concepts).reduce(0, +)
        let maxReviews = max(days.map(\.reviews).max() ?? 0, 1)

        return GlassCard {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("This week")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Spacer()
                    Text("Last 7 days")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textTertiary)
                }
                HStack(alignment: .top) {
                    insightStat("\(reviews)", label: "reviews", color: GRColor.accent)
                    insightStat(accuracy.map { "\(Int(($0 * 100).rounded()))%" } ?? "—", label: "accuracy", color: GRColor.textPrimary)
                    insightStat("\(concepts)", label: "concepts learned", color: GRColor.textPrimary)
                }
                HStack(alignment: .bottom, spacing: 10) {
                    ForEach(days) { day in
                        VStack(spacing: 6) {
                            RoundedRectangle(cornerRadius: 6, style: .continuous)
                                .fill(day.isToday ? GRColor.accent : GRColor.accentSoft)
                                .frame(height: max(6, 72 * CGFloat(day.reviews) / CGFloat(maxReviews)))
                            Text(day.label)
                                .font(GRType.micro)
                                .foregroundStyle(day.isToday ? GRColor.accent : GRColor.textTertiary)
                        }
                        .frame(maxWidth: .infinity)
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel("\(day.id): \(day.reviews) reviews")
                    }
                }
                .frame(height: 94, alignment: .bottom)
            }
        }
    }

    private func insightStat(_ value: String, label: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(value)
                .font(.system(size: 28, weight: .heavy, design: .rounded))
                .foregroundStyle(color)
                .minimumScaleFactor(0.7)
            Text(label)
                .font(GRType.micro)
                .foregroundStyle(GRColor.textTertiary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - Mastery by domain

    private var masteryCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Mastery by domain")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Spacer()
                    Text("Weakest first")
                        .font(GRType.caption.weight(.bold))
                        .foregroundStyle(GRColor.accent)
                }
                ForEach(domainMastery.prefix(5)) { item in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text(item.domain)
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textPrimary)
                            Text("· \(item.count)")
                                .font(GRType.micro)
                                .foregroundStyle(GRColor.textTertiary)
                            Spacer()
                            Text("\(Int((item.mastery * 100).rounded()))%")
                                .font(GRType.caption.weight(.bold))
                                .foregroundStyle(item.mastery < 0.4 ? GRColor.amber : GRColor.textSecondary)
                        }
                        GRProgressBar(value: item.mastery, tint: item.mastery < 0.4 ? GRColor.amber : (item.mastery < 0.6 ? GRColor.accentCyan : GRColor.accent))
                    }
                }
            }
        }
    }

    // MARK: - Heatmap

    private var activitySection: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Activity")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Spacer()
                    Text("Last 80 days")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textTertiary)
                }

                ActivityHeatmapGrid(dots: ActivityHeatmap.generate(from: stats?.dailyActivity ?? []))

                HStack(spacing: 6) {
                    Spacer()
                    Text("Less")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    ForEach(0..<5, id: \.self) { level in
                        RoundedRectangle(cornerRadius: 2, style: .continuous)
                            .fill(ActivityHeatmap.color(for: level))
                            .frame(width: 10, height: 10)
                    }
                    Text("More")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                }
            }
        }
    }

    // MARK: - Library

    private var libraryGrid: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Library")
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                libraryTile("Concepts", count: conceptsCount, icon: "lightbulb.fill", tone: .cyan, route: .concepts)
                libraryTile("Notes", count: notesCount, icon: "doc.text.fill", tone: .accent, route: .notes)
                libraryTile("Quizzes", count: quizCount, icon: "target", tone: .purple, route: .quizzes)
                libraryTile("Resources", count: uploadsCount, icon: "photo.on.rectangle", tone: .coral, route: .uploads)
                libraryTile("Books", count: booksCount, icon: "books.vertical.fill", tone: .amber, route: .library)
                libraryTile("Saved", count: savedCount, icon: "bookmark.fill", tone: .accent, route: .saved)
            }
        }
    }

    private func libraryTile(_ title: String, count: Int, icon: String, tone: GRTone, route: ProfileNavRoute) -> some View {
        Button {
            path.append(route)
        } label: {
            HStack(spacing: 12) {
                GRIconTile(systemImage: icon, tone: tone, size: 40)
                VStack(alignment: .leading, spacing: 0) {
                    Text("\(count)")
                        .font(GRType.title)
                        .foregroundStyle(GRColor.textPrimary)
                    Text(title)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
                Spacer(minLength: 0)
            }
            .padding(14)
            .grGlassEffect(in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .contentShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(title), \(count)")
    }

    // MARK: - Load

    @MainActor
    private func refresh() async {
        tokenPresent = await APIClient.shared.getAccessToken() != nil
        isLoadingStats = true
        defer { isLoadingStats = false }

        async let statsTask: Void = loadStats()
        async let scheduleTask: Void = loadSchedule()
        async let countsTask: Void = loadNestedCounts()
        async let graphTask: Void = loadGraphInsights()
        _ = await (statsTask, scheduleTask, countsTask, graphTask)
    }

    @MainActor
    private func loadStats() async {
        do {
            stats = try await APIClient.shared.fetchStats()
            statsError = nil
        } catch {
            statsError = APIError.userFacing(error, resource: "stats")
        }
    }

    @MainActor
    private func loadSchedule() async {
        do {
            schedule = try await APIClient.shared.fetchSchedule(days: 14)
            scheduleError = nil
        } catch {
            scheduleError = APIError.userFacing(error, resource: "schedule")
        }
    }

    @MainActor
    private func loadGraphInsights() async {
        guard let graph = try? await APIClient.shared.fetchGraph() else {
            conceptsCount = stats?.totalConcepts ?? conceptsCount
            return
        }
        conceptsCount = graph.nodes.count
        var buckets: [String: (sum: Double, count: Int)] = [:]
        for node in graph.nodes {
            let domain = (node.domain?.isEmpty == false ? node.domain : nil) ?? "General"
            let current = buckets[domain] ?? (0, 0)
            buckets[domain] = (current.sum + (node.masteryLevel ?? 0), current.count + 1)
        }
        domainMastery = buckets
            .map { DomainMastery(domain: $0.key, mastery: $0.value.sum / Double(max($0.value.count, 1)), count: $0.value.count) }
            .sorted { $0.mastery < $1.mastery }
    }

    @MainActor
    private func loadNestedCounts() async {
        async let notesR = softNotesCount()
        async let uploadsR = softUploadsCount()
        async let quizzesR = softQuizCount()
        async let booksR = softBooksCount()
        async let savedR = softSavedCount()
        let (n, u, q, b, s) = await (notesR, uploadsR, quizzesR, booksR, savedR)
        notesCount = n
        uploadsCount = u
        quizCount = q
        booksCount = b
        savedCount = s
    }

    private func softNotesCount() async -> Int {
        do {
            let r = try await APIClient.shared.fetchNotes(limit: 100)
            return r.notes.filter { ($0.resourceType ?? "").lowercased() != "book" }.count
        } catch {
            return stats?.totalNotes ?? notesCount
        }
    }

    private func softUploadsCount() async -> Int {
        (try? await APIClient.shared.fetchUploads(limit: 50).total) ?? uploadsCount
    }

    private func softQuizCount() async -> Int {
        (try? await APIClient.shared.fetchQuizHistory().quizzes.count) ?? quizCount
    }

    private func softBooksCount() async -> Int {
        (try? await APIClient.shared.fetchLibraryBooks().total) ?? booksCount
    }

    private func softSavedCount() async -> Int {
        (try? await APIClient.shared.fetchSavedItems().total) ?? savedCount
    }
}

// MARK: - Saved items

struct SavedItemsListView: View {
    @State private var items: [SavedItem] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var expanded: Set<String> = []

    var body: some View {
        ZStack {
            GRColor.canvas.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    GRScreenHeader(title: "Saved", subtitle: "\(items.count) card\(items.count == 1 ? "" : "s") you bookmarked")
                    Group {
                        if isLoading && items.isEmpty {
                            ProgressView().tint(GRColor.accent).frame(maxWidth: .infinity, minHeight: 120)
                        } else if let errorMessage, items.isEmpty {
                            GRBanner(systemImage: "exclamationmark.triangle.fill", title: "Couldn’t load saved cards", subtitle: errorMessage, tone: .warning)
                        } else if items.isEmpty {
                            GRBanner(systemImage: "bookmark", title: "Nothing saved yet", subtitle: "Tap the bookmark on any card during review to keep it here.", tone: .accent)
                        }
                        ForEach(items) { item in
                            Button {
                                if expanded.contains(item.id) { expanded.remove(item.id) } else { expanded.insert(item.id) }
                            } label: {
                                VStack(alignment: .leading, spacing: 8) {
                                    HStack(alignment: .top, spacing: 12) {
                                        GRIconTile(
                                            systemImage: item.itemCategory == "flashcard" ? "rectangle.on.rectangle" : "checklist",
                                            tone: item.itemCategory == "flashcard" ? .accent : .purple
                                        )
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(item.displayTitle)
                                                .font(GRType.headline)
                                                .foregroundStyle(GRColor.textPrimary)
                                                .multilineTextAlignment(.leading)
                                            Text([item.topic, ProfileDateFormat.short(item.createdAt)].compactMap { $0 }.joined(separator: " · "))
                                                .font(GRType.caption)
                                                .foregroundStyle(GRColor.textTertiary)
                                        }
                                        Spacer(minLength: 0)
                                        Image(systemName: expanded.contains(item.id) ? "chevron.up" : "chevron.down")
                                            .font(.system(size: 12, weight: .semibold))
                                            .foregroundStyle(GRColor.textTertiary)
                                    }
                                    if expanded.contains(item.id) {
                                        if let answer = item.displayAnswer, !answer.isEmpty {
                                            Text(answer)
                                                .font(GRType.body)
                                                .foregroundStyle(GRColor.accent)
                                        }
                                        if let explanation = item.explanation, !explanation.isEmpty {
                                            Text(explanation)
                                                .font(GRType.caption)
                                                .foregroundStyle(GRColor.textSecondary)
                                        }
                                    }
                                }
                                .padding(14)
                                .grGlassEffect(in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 20)
                }
            }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            items = try await APIClient.shared.fetchSavedItems().items
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "saved cards")
        }
    }
}

// MARK: - Heatmap (matches web generateHeatmap)

enum ActivityHeatmap {
    struct Dot: Identifiable, Hashable {
        let id: String
        let date: String
        let level: Int
    }

    /// Web ProfileScreen uses last 80 days + level thresholds on reviews_completed.
    static func generate(from daily: [DailyActivity], days: Int = 80) -> [Dot] {
        var activityMap: [String: Int] = [:]
        for day in daily {
            let key = day.date.split(separator: "T").first.map(String.init) ?? day.date
            activityMap[key] = level(for: day.reviewsCompleted)
        }

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0) ?? .gmt
        let today = calendar.startOfDay(for: Date())
        var dots: [Dot] = []
        dots.reserveCapacity(days)

        for offset in stride(from: days - 1, through: 0, by: -1) {
            guard let date = calendar.date(byAdding: .day, value: -offset, to: today) else { continue }
            let dateStr = Self.dayKey(date)
            dots.append(Dot(id: dateStr, date: dateStr, level: activityMap[dateStr] ?? 0))
        }
        return dots
    }

    static func level(for reviewsCompleted: Int) -> Int {
        if reviewsCompleted > 30 { return 4 }
        if reviewsCompleted > 15 { return 3 }
        if reviewsCompleted > 5 { return 2 }
        if reviewsCompleted > 0 { return 1 }
        return 0
    }

    static func color(for level: Int) -> Color {
        // Match frontend/src/index.css .heatmap-0 … .heatmap-4 (lime #B6FF2E)
        switch level {
        case 1: return GRColor.accent.opacity(0.20)
        case 2: return GRColor.accent.opacity(0.40)
        case 3: return GRColor.accent.opacity(0.60)
        case 4: return GRColor.accent.opacity(0.85)
        default: return Color.white.opacity(0.05)
        }
    }

    private static func dayKey(_ date: Date) -> String {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(secondsFromGMT: 0)
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: date)
    }
}

struct ActivityHeatmapGrid: View {
    let dots: [ActivityHeatmap.Dot]
    private let columns = Array(repeating: GridItem(.flexible(), spacing: 3), count: 16)

    var body: some View {
        LazyVGrid(columns: columns, spacing: 3) {
            ForEach(dots) { dot in
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(ActivityHeatmap.color(for: dot.level))
                    .aspectRatio(1, contentMode: .fit)
                    .accessibilityLabel("\(dot.date), level \(dot.level)")
            }
        }
    }
}

#Preview { ProfileView().preferredColorScheme(.dark) }
