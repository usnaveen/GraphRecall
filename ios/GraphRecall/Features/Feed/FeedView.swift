import SwiftUI

struct FeedView: View {
    @State private var model = FeedViewModel()
    @State private var contentReady = false
    @State private var activeSession: SessionLaunch?
    @Environment(AppRouter.self) private var router

    var body: some View {
        ZStack {
            GRColor.canvas.ignoresSafeArea()
            GRBackdropGlow()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header

                    Group {
                        if model.isLoading && model.items.isEmpty {
                            ProgressView()
                                .tint(GRColor.accent)
                                .frame(maxWidth: .infinity, minHeight: 160)
                        } else {
                            goalCard
                            statsRow
                            banners
                            if !model.items.isEmpty {
                                focusSessions
                                upNextSection
                            } else {
                                emptyState
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                }
                .padding(.bottom, GRLayout.dockClearance)
            }
            .opacity(contentReady ? 1 : 0)
            .animation(.easeOut(duration: 0.18), value: contentReady)
            .refreshable { await model.load() }

            if let banner = model.softBanner {
                VStack {
                    Spacer()
                    GRToast(message: banner, isError: Self.isErrorCopy(banner))
                        .padding(.horizontal, 24)
                        .padding(.bottom, GRLayout.dockClearance + 8)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                .animation(.spring(response: 0.35, dampingFraction: 0.85), value: model.softBanner)
                .onTapGesture { model.dismissSoftBanner() }
            }
        }
        .task {
            await model.load()
            contentReady = true
            consumePendingReview()
        }
        .onChange(of: router.pendingStartReview) { _, _ in consumePendingReview() }
        .fullScreenCover(item: $activeSession) { launch in
            ReviewSessionView(
                feed: model,
                items: launch.items,
                focusLabel: model.focusDomain.map(Self.domainTitle),
                onFinish: { Task { await model.load() } }
            )
            .environment(router)
        }
        .onReceive(NotificationCenter.default.publisher(for: .grDumpCompleted)) { _ in
            Task { await model.load() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .grFeedShouldReload)) { _ in
            Task { await model.load() }
        }
    }

    /// Widget / `graphrecall://review` asked for a session.
    private func consumePendingReview() {
        guard router.pendingStartReview, contentReady, !model.isLoading else { return }
        router.pendingStartReview = false
        guard activeSession == nil, !model.sessionQueue.isEmpty else { return }
        startSession(with: model.sessionQueue)
    }

    // MARK: - Header

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            GRScreenHeader(title: "Today", subtitle: headerSubtitle)
            HStack(spacing: 8) {
                GRIconButton(systemImage: "magnifyingglass", tint: GRColor.textPrimary, accessibilityLabel: "Search") {
                    router.showSearch = true
                }
                GRIconButton(systemImage: "arrow.clockwise", accessibilityLabel: "Refresh") {
                    Task { await model.load() }
                }
            }
            .padding(.trailing, 20)
            .padding(.top, 14)
        }
    }

    private var headerSubtitle: String {
        let date = Date().formatted(.dateTime.weekday(.wide).month(.abbreviated).day())
        if model.isDemoMode { return "\(date) · demo cards" }
        return "\(date) · \(model.dueTotal) due"
    }

    // MARK: - Goal

    private var goalCard: some View {
        GlassCard(cornerRadius: 22) {
            HStack(spacing: 18) {
                GRProgressRing(progress: model.goalProgress, lineWidth: 9) {
                    VStack(spacing: 0) {
                        Text(model.progressLabel)
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
                    if model.streak > 0 {
                        Label("\(model.streak)-day streak", systemImage: "flame.fill")
                            .font(GRType.caption.weight(.bold))
                            .foregroundStyle(GRColor.amber)
                    }
                    Text(goalTitle)
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(goalSubtitle)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                    Button {
                        startSession(with: model.sessionQueue)
                    } label: {
                        Label(model.sessionQueue.isEmpty ? "Queue empty" : "Start review", systemImage: "play.fill")
                    }
                    .buttonStyle(GRButtonStyle(kind: .primary, compact: true))
                    .disabled(model.sessionQueue.isEmpty)
                    .accessibilityIdentifier("today.startReview")
                    .padding(.top, 2)
                }
            }
        }
    }

    private var goalTitle: String {
        if model.sessionQueue.isEmpty { return model.completedToday > 0 ? "All clear for now" : "Nothing due yet" }
        if model.remainingToGoal == 0 { return "Goal reached — keep the streak warm" }
        return "\(model.remainingToGoal) more to hit your goal"
    }

    private var goalSubtitle: String {
        let count = model.sessionQueue.count
        guard count > 0 else { return "Dump concepts in Create to fill your queue." }
        let minutes = max(1, Int((Double(count) * 20 / 60).rounded()))
        return "≈ \(minutes) min · \(count) card\(count == 1 ? "" : "s") queued"
    }

    private var statsRow: some View {
        HStack(spacing: 10) {
            GRStatChip(title: "Due", value: "\(model.dueTotal)", systemImage: "tray.full.fill")
            GRStatChip(title: "Done", value: "\(model.completedToday)", systemImage: "checkmark.circle.fill")
            GRStatChip(title: "Retention", value: model.retentionLabel, systemImage: "target")
        }
    }

    // MARK: - Banners

    @ViewBuilder
    private var banners: some View {
        if model.isDemoMode {
            GRBanner(
                systemImage: "sparkles",
                title: "Demo mode",
                subtitle: model.errorMessage ?? "Sample teach cards for Simulator / offline demos. Grades stay local.",
                tone: .warning
            )
        }
        if model.dumpBannerCount > 0 {
            Button {
                startSession(with: model.items)
            } label: {
                GRBanner(
                    systemImage: "tray.and.arrow.down.fill",
                    title: "\(model.dumpBannerCount) new teach card\(model.dumpBannerCount == 1 ? "" : "s")",
                    subtitle: "Fresh from your concept dump — tap to review them first",
                    tone: .accent
                )
            }
            .buttonStyle(.plain)
        }
        if (model.isOffline || model.pendingFlushCount > 0) && !model.isDemoMode {
            GRBanner(
                systemImage: model.isOffline ? "wifi.slash" : "arrow.triangle.2.circlepath",
                title: model.isOffline ? "Offline mode" : "Syncing reviews",
                subtitle: model.pendingFlushCount > 0
                    ? "\(model.pendingFlushCount) review(s) waiting to sync"
                    : "Showing cached cards — stats may be stale",
                tone: .accent
            )
        }
    }

    // MARK: - Focus sessions

    private var focusSessions: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Focus sessions")
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    GRChip(
                        title: "All due · \(model.items.count)",
                        systemImage: "square.stack.3d.up.fill",
                        style: model.focusDomain == nil ? .selected : .plain
                    ) {
                        withAnimation(.easeOut(duration: 0.2)) { model.focusDomain = nil }
                        GRHaptics.tap()
                    }
                    ForEach(model.focusDomains, id: \.name) { entry in
                        GRChip(
                            title: "\(Self.domainTitle(entry.name)) · \(entry.count)",
                            style: model.focusDomain == entry.name ? .selected : .plain
                        ) {
                            withAnimation(.easeOut(duration: 0.2)) {
                                model.focusDomain = model.focusDomain == entry.name ? nil : entry.name
                            }
                            GRHaptics.tap()
                        }
                    }
                }
                .padding(.horizontal, 20)
            }
            .padding(.horizontal, -20)
        }
    }

    // MARK: - Up next

    private var upNextSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(
                title: "Up next",
                actionTitle: model.sessionQueue.count > model.upNext.count ? "Review all \(model.sessionQueue.count)" : nil,
                action: { startSession(with: model.sessionQueue) }
            )
            if model.upNext.isEmpty {
                GRBanner(systemImage: "checkmark.seal.fill", title: "Nothing in this focus", subtitle: "Pick another domain or review everything due.", tone: .accent)
            }
            ForEach(model.upNext) { item in
                Button {
                    var queue = model.sessionQueue
                    if let idx = queue.firstIndex(where: { $0.id == item.id }) {
                        queue.remove(at: idx)
                        queue.insert(item, at: 0)
                    }
                    startSession(with: queue)
                } label: {
                    GRListRow(
                        title: item.prompt,
                        subtitle: rowSubtitle(item),
                        meta: item.isOverdue ? "Overdue" : "Due",
                        metaColor: item.isOverdue ? GRColor.warning : GRColor.accent,
                        systemImage: item.itemType.systemImage,
                        tone: item.itemType.tone
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func rowSubtitle(_ item: FeedItem) -> String {
        let context = item.conceptName ?? item.domain.map(Self.domainTitle) ?? ""
        return context.isEmpty ? item.itemType.displayLabel : "\(item.itemType.displayLabel) · \(context)"
    }

    private var emptyState: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                Text(model.completedToday > 0 ? "Session clear" : "Nothing due")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.accent)
                Text(model.errorMessage ?? "Dump concepts in Create, or check back when cards are due.")
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)
                Button {
                    router.select(.create)
                } label: {
                    Label("Add concepts", systemImage: "plus")
                }
                .buttonStyle(GRButtonStyle(kind: .ghost, fullWidth: false, compact: true))
            }
        }
    }

    // MARK: - Helpers

    private func startSession(with items: [FeedItem]) {
        guard !items.isEmpty else { return }
        GRHaptics.tap()
        activeSession = SessionLaunch(items: items)
    }

    static func domainTitle(_ raw: String) -> String {
        raw == "concept_dump" ? "Concept dump" : raw
    }

    private static func isErrorCopy(_ message: String) -> Bool {
        ["can\u{2019}t", "couldn\u{2019}t", "sign in", "failed", "not found"].contains {
            message.localizedCaseInsensitiveContains($0)
        }
    }
}

#Preview {
    FeedView()
        .environment(AppRouter())
        .preferredColorScheme(.dark)
}
