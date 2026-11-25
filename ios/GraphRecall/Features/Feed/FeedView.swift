import SwiftUI

/// The feed: content first, no goal rings or counters — those live in Profile now.
/// Reels (one card at a time) or a scrolling timeline, switchable in Settings and from the
/// button in the corner.
struct FeedView: View {
    @State private var model = FeedViewModel()
    @State private var contentReady = false
    @State private var activeSession: SessionLaunch?
    @State private var showAgentInsights = false
    @State private var dueLater: [LaterItem] = []
    @State private var dueCardHeight: CGFloat = 0
    @State private var showAgentInbox = false
    private let agentBridge = AgentBridgeCapability.shared
    @AppStorage(GRSettingsKey.feedStyle) private var feedStyleRaw = FeedStyle.reels.rawValue
    @Environment(AppRouter.self) private var router

    enum FeedStyle: String {
        case reels, posts
    }

    private var style: FeedStyle {
        FeedStyle(rawValue: feedStyleRaw) ?? .reels
    }

    var body: some View {
        ZStack(alignment: .top) {
            GRColor.canvas.ignoresSafeArea()
            GRBackdropGlow()

            Group {
                if model.isLoading && model.queue.isEmpty {
                    ProgressView()
                        .tint(GRColor.accent)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if model.queue.isEmpty {
                    emptyState
                        .padding(.horizontal, 20)
                        .frame(maxHeight: .infinity)
                } else {
                    switch style {
                    case .reels: FeedReelView(model: model)
                    case .posts: FeedPostsView(model: model)
                    }
                }
            }
            // A due "later" card pushes the feed down instead of covering the current card.
            .safeAreaInset(edge: .top, spacing: 0) {
                Color.clear.frame(height: dueLater.isEmpty ? 0 : dueCardHeight + 10)
            }
            .opacity(contentReady ? 1 : 0)
            .animation(.easeOut(duration: 0.18), value: contentReady)

            VStack(spacing: 10) {
                topBar
                if !dueLater.isEmpty {
                    LaterDueCard(items: $dueLater)
                        .padding(.horizontal, 16)
                        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { dueCardHeight = $0 }
                }
            }
            .animation(.spring(response: 0.35, dampingFraction: 0.85), value: dueLater)

            if let banner = model.softBanner {
                VStack {
                    Spacer()
                    GRToast(message: banner, isError: Self.isErrorCopy(banner))
                        .padding(.horizontal, 24)
                        .padding(.bottom, 8)
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
            await model.loadRevisitPool()
            await loadDueLater()
            await agentBridge.refresh()
        }
        // Agent bridge: curated cards waiting for approval + "ask my agent" answers.
        .sheet(isPresented: $showAgentInbox, onDismiss: {
            Task { await agentBridge.refreshPendingCount() }
        }) {
            AgentInboxView()
                .presentationDragIndicator(.visible)
        }
        .onChange(of: router.pendingStartReview) { _, _ in consumePendingReview() }
        .fullScreenCover(item: $activeSession) { launch in
            ReviewSessionView(
                feed: model,
                items: launch.items,
                focusLabel: nil,
                onFinish: { Task { await model.load() } }
            )
            .environment(router)
        }
        .sheet(isPresented: $showAgentInsights) {
            AgentInsightsSheet(model: model)
                .environment(router)
                .presentationDragIndicator(.visible)
        }
        .onReceive(NotificationCenter.default.publisher(for: .grDumpCompleted)) { _ in
            Task { await model.load() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .grFeedShouldReload)) { _ in
            Task { await model.load(); await loadDueLater() }
        }
    }

    // MARK: - Chrome

    /// Floating controls only — the feed itself stays full-bleed.
    private var topBar: some View {
        HStack(spacing: 8) {
            if model.isDemoMode {
                Text("Demo cards")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.accent)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .grGlassEffect(in: Capsule())
            }
            Spacer()
            if agentBridge.isAvailable {
                AgentInboxButton(pendingCount: agentBridge.pendingCount) {
                    GRHaptics.tap()
                    showAgentInbox = true
                }
            }
            GRIconButton(
                systemImage: "sparkles",
                tint: model.agentInsights.isEmpty ? GRColor.textSecondary : GRColor.accent,
                size: 38,
                accessibilityLabel: "Agent Inbox"
            ) {
                showAgentInsights = true
                GRHaptics.tap()
            }
            GRIconButton(
                systemImage: style == .reels ? "rectangle.stack" : "rectangle.portrait.on.rectangle.portrait",
                tint: GRColor.textSecondary,
                size: 38,
                accessibilityLabel: style == .reels ? "Switch to scrolling posts" : "Switch to one card at a time"
            ) {
                withAnimation(.easeOut(duration: 0.2)) {
                    feedStyleRaw = style == .reels ? FeedStyle.posts.rawValue : FeedStyle.reels.rawValue
                }
                GRHaptics.tap()
            }
            GRIconButton(systemImage: "magnifyingglass", tint: GRColor.textSecondary, size: 38, accessibilityLabel: "Search") {
                router.showSearch = true
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 6)
    }

    private var emptyState: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                Text("Nothing to show yet")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.accent)
                Text(model.errorMessage ?? "Dump a PDF, link or a few notes in Create and your feed fills up.")
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)
                Button {
                    router.select(.create)
                } label: {
                    Label("Add something", systemImage: "plus")
                }
                .grButton(.ghost, fullWidth: false, compact: true)
            }
        }
    }

    // MARK: - Helpers

    /// Saved-for-later items whose time has come. Best effort: the feed never waits on this.
    private func loadDueLater() async {
        guard let items = try? await APIClient.shared.dueLaterItems() else { return }
        dueLater = items
    }

    /// Widget / `graphrecall://review` / Profile asked for a focused review session.
    private func consumePendingReview() {
        guard router.pendingStartReview, contentReady, !model.isLoading else { return }
        router.pendingStartReview = false
        guard activeSession == nil, !model.items.isEmpty else { return }
        GRHaptics.tap()
        activeSession = SessionLaunch(items: model.items)
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
