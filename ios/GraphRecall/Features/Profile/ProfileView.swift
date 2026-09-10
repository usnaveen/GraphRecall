import SwiftUI

enum ProfileNavRoute: Hashable {
    case library
    case notes
    case concepts
    case uploads
    case quizzes
}

struct ProfileView: View {
    var openLibraryToken: Int = 0

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
    @State private var path = NavigationPath()

    var body: some View {
        NavigationStack(path: $path) {
            ZStack {
                Circle()
                    .fill(GRColor.accent.opacity(0.10))
                    .frame(width: 240, height: 240)
                    .blur(radius: 50)
                    .offset(x: -100, y: -160)
                    .allowsHitTesting(false)

                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        header

                        identityCard
                            .padding(.horizontal, 20)

                        dueChips
                            .padding(.horizontal, 20)

                        nestedStatsGrid
                            .padding(.horizontal, 20)

                        CalendarScheduleView(schedule: schedule)
                            .padding(.horizontal, 20)

                        if let scheduleError {
                            Text(scheduleError)
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.warning)
                                .padding(.horizontal, 20)
                        }

                        activitySection
                            .padding(.horizontal, 20)
                    }
                    .padding(.bottom, GRLayout.dockClearance)
                }
            }
            .navigationDestination(for: ProfileNavRoute.self) { route in
                switch route {
                case .library:
                    LibraryView()
                case .notes:
                    ProfileNotesListView()
                case .concepts:
                    ProfileConceptsListView()
                case .uploads:
                    ProfileUploadsListView()
                case .quizzes:
                    ProfileQuizzesListView()
                }
            }
            .navigationBarHidden(true)
        }
        .task { await refresh() }
        .refreshable { await refresh() }
        .onChange(of: openLibraryToken) { _, newValue in
            guard newValue > 0 else { return }
            path.append(ProfileNavRoute.library)
        }
        .sheet(isPresented: $showSettings) {
            ProfileSettingsSheet(tokenPresent: $tokenPresent)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }

    // MARK: - Header / identity

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            GRScreenHeader(title: "Profile", subtitle: "Streak, schedule & library")
            Button {
                showSettings = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(GRColor.textSecondary)
                    .padding(10)
                    .grGlassEffect(.interactive, in: Circle())
            }
            .accessibilityLabel("Settings")
            .padding(.trailing, 20)
            .padding(.top, 12)
        }
    }

    private var identityCard: some View {
        GlassCard {
            HStack(spacing: 14) {
                ZStack {
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [GRColor.accent, GRColor.accentCyan],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .frame(width: 64, height: 64)
                    Circle()
                        .fill(GRColor.canvas)
                        .frame(width: 60, height: 60)
                    Text(tokenPresent ? "G" : "?")
                        .font(GRType.title)
                        .foregroundStyle(GRColor.textPrimary)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(tokenPresent ? "Signed in" : "Not signed in")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Text(tokenPresent ? "Demo session · GraphRecall" : "Sign in from Settings to sync reviews")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                    HStack(spacing: 6) {
                        Circle()
                            .fill(tokenPresent ? GRColor.accent : GRColor.warning.opacity(0.8))
                            .frame(width: 7, height: 7)
                        Text(tokenPresent ? "Session active" : "Offline identity stub")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                        if let streak = stats?.streakDays, streak > 0 {
                            Text("·")
                                .foregroundStyle(GRColor.textTertiary)
                            Image(systemName: "flame.fill")
                                .font(.system(size: 10))
                                .foregroundStyle(GRColor.accent)
                            Text("\(streak)d streak")
                                .font(GRType.micro)
                                .foregroundStyle(GRColor.textTertiary)
                        }
                    }
                    .padding(.top, 2)
                }
                Spacer(minLength: 0)
            }
        }
    }

    // MARK: - Due chips (NAV-26 keep)

    private var dueChips: some View {
        let due = stats?.dueToday ?? 0
        let done = stats?.completedToday ?? 0
        let overdue = stats?.overdue ?? 0

        return VStack(alignment: .leading, spacing: 10) {
            if isLoadingStats && stats == nil {
                ProgressView()
                    .tint(GRColor.accent)
                    .frame(maxWidth: .infinity, minHeight: 56)
            } else {
                HStack(spacing: 10) {
                    miniChip(title: "Due", value: "\(due)", icon: "tray.full.fill")
                    miniChip(title: "Done", value: "\(done)", icon: "checkmark.circle.fill")
                    miniChip(title: "Overdue", value: "\(overdue)", icon: "exclamationmark.triangle.fill")
                }
            }
            if let statsError {
                Text(statsError)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.warning)
            }
        }
    }

    private func miniChip(title: String, value: String, icon: String) -> some View {
        GlassCard(cornerRadius: 14) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 4) {
                    Image(systemName: icon)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(GRColor.accent)
                    Text(title)
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                }
                Text(value)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
            }
        }
    }

    // MARK: - Nested list stats (web ProfileScreen grid)

    private var nestedStatsGrid: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
            drillCard(
                title: "Quizzes",
                count: quizCount,
                icon: "target",
                color: Color(red: 0.61, green: 0.35, blue: 0.71),
                route: .quizzes
            )
            drillCard(
                title: "Notes",
                count: notesCount,
                icon: "doc.text.fill",
                color: GRColor.accent,
                route: .notes
            )
            drillCard(
                title: "Concepts",
                count: conceptsCount,
                icon: "brain.head.profile",
                color: GRColor.accentCyan,
                route: .concepts
            )
            drillCard(
                title: "Resources",
                count: uploadsCount,
                icon: "photo.on.rectangle",
                color: Color(red: 1.0, green: 0.42, blue: 0.42),
                route: .uploads
            )
            drillCard(
                title: "Books",
                count: booksCount,
                icon: "books.vertical.fill",
                color: Color(red: 0.96, green: 0.62, blue: 0.04),
                route: .library,
                wide: true
            )
        }
    }

    private func drillCard(
        title: String,
        count: Int,
        icon: String,
        color: Color,
        route: ProfileNavRoute,
        wide: Bool = false
    ) -> some View {
        Button {
            path.append(route)
        } label: {
            GlassCard(cornerRadius: 16) {
                VStack(spacing: 10) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .fill(color.opacity(0.18))
                            .frame(width: 40, height: 40)
                        Image(systemName: icon)
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(color)
                    }
                    Text("\(count)")
                        .font(GRType.title)
                        .foregroundStyle(GRColor.textPrimary)
                    Text(title)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(title), \(count)")
        .gridCellColumns(wide ? 2 : 1)
    }

    // MARK: - Heatmap (NAV-26)

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

    // MARK: - Load

    @MainActor
    private func refresh() async {
        tokenPresent = await APIClient.shared.getAccessToken() != nil
        isLoadingStats = true
        defer { isLoadingStats = false }

        async let statsTask: Void = loadStats()
        async let scheduleTask: Void = loadSchedule()
        async let countsTask: Void = loadNestedCounts()
        _ = await (statsTask, scheduleTask, countsTask)
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
    private func loadNestedCounts() async {
        async let notesR = softNotesCount()
        async let conceptsR = softConceptsCount()
        async let uploadsR = softUploadsCount()
        async let quizzesR = softQuizCount()
        async let booksR = softBooksCount()
        let (n, c, u, q, b) = await (notesR, conceptsR, uploadsR, quizzesR, booksR)
        notesCount = n
        conceptsCount = c
        uploadsCount = u
        quizCount = q
        booksCount = b
    }

    private func softNotesCount() async -> Int {
        do {
            let r = try await APIClient.shared.fetchNotes(limit: 100)
            return r.notes.filter { ($0.resourceType ?? "").lowercased() != "book" }.count
        } catch {
            return stats?.totalNotes ?? notesCount
        }
    }

    private func softConceptsCount() async -> Int {
        do {
            return try await APIClient.shared.fetchProfileConcepts().count
        } catch {
            return stats?.totalConcepts ?? conceptsCount
        }
    }

    private func softUploadsCount() async -> Int {
        do {
            return try await APIClient.shared.fetchUploads(limit: 50).total
        } catch {
            return uploadsCount
        }
    }

    private func softQuizCount() async -> Int {
        do {
            return try await APIClient.shared.fetchQuizHistory().quizzes.count
        } catch {
            return quizCount
        }
    }

    private func softBooksCount() async -> Int {
        do {
            return try await APIClient.shared.fetchLibraryBooks().total
        } catch {
            return booksCount
        }
    }
}

// MARK: - Settings (developer tools behind gear)

struct ProfileSettingsSheet: View {
    @Binding var tokenPresent: Bool
    @AppStorage("graphrecall.apiBase") private var apiBase: String = APIConfig.baseURL.absoluteString
    @State private var cacheClearedMessage: String?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()

                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        GlassCard {
                            VStack(alignment: .leading, spacing: 10) {
                                Text("API base URL")
                                    .font(GRType.headline)
                                    .foregroundStyle(GRColor.textPrimary)
                                TextField("http://127.0.0.1:8000", text: $apiBase)
                                    .textInputAutocapitalization(.never)
                                    .autocorrectionDisabled()
                                    .padding(12)
                                    .background(
                                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                                            .fill(GRColor.fillSubtle)
                                    )
                                    .foregroundStyle(GRColor.textPrimary)
                                    .font(GRType.body)
                                Text("Used by the iOS client for FastAPI calls.")
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.textSecondary)
                            }
                        }

                        GlassCard {
                            VStack(alignment: .leading, spacing: 10) {
                                Text("Session")
                                    .font(GRType.headline)
                                    .foregroundStyle(GRColor.textPrimary)
                                HStack {
                                    Circle()
                                        .fill(tokenPresent ? GRColor.accent : GRColor.warning.opacity(0.8))
                                        .frame(width: 8, height: 8)
                                    Text(tokenPresent ? "Signed in (demo token)" : "Not signed in")
                                        .font(GRType.body)
                                        .foregroundStyle(GRColor.textSecondary)
                                }
                                Text("Concept Dump and feed sync need auth against your backend.")
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.textTertiary)

                                if tokenPresent {
                                    Button {
                                        Task {
                                            await APIClient.shared.setAccessToken(nil)
                                            tokenPresent = await APIClient.shared.getAccessToken() != nil
                                        }
                                    } label: {
                                        Text("Sign out")
                                            .font(GRType.headline)
                                            .frame(maxWidth: .infinity)
                                            .padding(.vertical, 12)
                                            .foregroundStyle(GRColor.textPrimary)
                                            .background(
                                                RoundedRectangle(cornerRadius: 14, style: .continuous)
                                                    .fill(GRColor.fillSubtle)
                                            )
                                    }
                                    .padding(.top, 4)
                                } else {
                                    Button {
                                        Task {
                                            await APIClient.shared.setAccessToken("demo-local-token")
                                            tokenPresent = await APIClient.shared.getAccessToken() != nil
                                        }
                                    } label: {
                                        Text("Sign in (demo token)")
                                            .font(GRType.headline)
                                            .frame(maxWidth: .infinity)
                                            .padding(.vertical, 12)
                                            .foregroundStyle(GRColor.canvas)
                                            .background(
                                                RoundedRectangle(cornerRadius: 14, style: .continuous)
                                                    .fill(GRColor.accent)
                                            )
                                    }
                                    .padding(.top, 4)
                                }
                            }
                        }

                        GlassCard {
                            VStack(alignment: .leading, spacing: 12) {
                                Text("Offline cache")
                                    .font(GRType.headline)
                                    .foregroundStyle(GRColor.textPrimary)
                                Button("Clear offline review cache") {
                                    Task {
                                        await OfflineReviewStore.shared.clearAll()
                                        cacheClearedMessage = "Offline cache cleared"
                                    }
                                }
                                .font(GRType.body)
                                .foregroundStyle(GRColor.accent)
                                if let cacheClearedMessage {
                                    Text(cacheClearedMessage)
                                        .font(GRType.caption)
                                        .foregroundStyle(GRColor.textSecondary)
                                }
                            }
                        }

                        GlassCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("About")
                                    .font(GRType.headline)
                                    .foregroundStyle(GRColor.textPrimary)
                                Text("GraphRecall")
                                    .font(GRType.body)
                                    .foregroundStyle(GRColor.textPrimary)
                                Text("Version 0.1.0 · Bundle com.usnaveen.graphrecall")
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.textSecondary)
                            }
                        }
                    }
                    .padding(20)
                    .padding(.bottom, 24)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .foregroundStyle(GRColor.accent)
                }
            }
        }
        .preferredColorScheme(.dark)
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
        case 1: return Color(red: 182 / 255, green: 255 / 255, blue: 46 / 255).opacity(0.20)
        case 2: return Color(red: 182 / 255, green: 255 / 255, blue: 46 / 255).opacity(0.40)
        case 3: return Color(red: 182 / 255, green: 255 / 255, blue: 46 / 255).opacity(0.60)
        case 4: return Color(red: 182 / 255, green: 255 / 255, blue: 46 / 255).opacity(0.85)
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
