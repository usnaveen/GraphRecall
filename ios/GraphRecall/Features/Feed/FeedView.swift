import SwiftUI

/// The feed: content first, no goal rings or counters — those live in Profile now.
/// Posts (cards one after another at their natural height, the default since 2026-11) or reels
/// (one card per screen), switchable in Settings and from the toolbar.
struct FeedView: View {
    @State private var model = FeedViewModel()
    @State private var contentReady = false
    @State private var activeSession: SessionLaunch?
    @State private var showAgentHub = false
    @State private var dueLater: [LaterItem] = []
    private let agentBridge = AgentBridgeCapability.shared
    @AppStorage(GRSettingsKey.feedStyle) private var feedStyleRaw = FeedStyle.posts.rawValue
    /// One-time move to posts for installs that stored the old reels default.
    @AppStorage(GRSettingsKey.feedStylePostsMigrated) private var postsMigrated = false
    @Environment(AppRouter.self) private var router

    enum FeedStyle: String {
        case reels, posts
    }

    private var style: FeedStyle {
        FeedStyle(rawValue: feedStyleRaw) ?? .posts
    }

    var body: some View {
        NavigationStack {
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
                        case .posts:
                            // Scrolls under the system toolbar and tab bar; their own scroll-edge
                            // effect keeps it readable, so the feed draws no bars or fades of its own.
                            FeedPostsView(model: model, dueLater: $dueLater)
                        case .reels:
                            GeometryReader { geo in
                                FeedReelView(model: model, bottomInset: geo.safeAreaInsets.bottom)
                                    .ignoresSafeArea(edges: .bottom)
                            }
                            // A due reminder sits above the page instead of covering it.
                            .safeAreaInset(edge: .top, spacing: 0) {
                                if !dueLater.isEmpty {
                                    LaterDueCard(items: $dueLater)
                                        .padding(.horizontal, 16)
                                        .padding(.bottom, 10)
                                }
                            }
                        }
                    }
                }
                .opacity(contentReady ? 1 : 0)
                .animation(.easeOut(duration: 0.18), value: contentReady)
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
            .toolbar { feedToolbar }
            .navigationBarTitleDisplayMode(.inline)
        }
        .onAppear {
            if !postsMigrated {
                feedStyleRaw = FeedStyle.posts.rawValue
                postsMigrated = true
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
        // One inbox for both agents: always-on insights, and outside-agent suggestions to approve.
        .sheet(isPresented: $showAgentHub, onDismiss: {
            Task { await agentBridge.refreshPendingCount() }
        }) {
            AgentHubSheet(
                feed: model,
                showsSuggestions: agentBridge.isAvailable,
                startOn: agentBridge.pendingCount > 0 ? .suggestions : .insights
            )
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

    /// System toolbar: real Liquid Glass buttons, grouped by the system, with the native scroll-edge
    /// effect where the feed passes under them.
    @ToolbarContentBuilder
    private var feedToolbar: some ToolbarContent {
        if model.isDemoMode {
            ToolbarItem(placement: .topBarLeading) {
                Text("Demo cards")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.accent)
                    .lineLimit(1)
                    .fixedSize() // the toolbar otherwise squeezes it into a circle ("Dem / o / car…")
                    .padding(.horizontal, 6)
                    .accessibilityIdentifier("feed.demoBadge")
            }
        }
        ToolbarItemGroup(placement: .topBarTrailing) {
            Button {
                GRHaptics.tap()
                showAgentHub = true
            } label: {
                Image(systemName: agentInboxCount > 0 ? "tray.full" : "tray")
                    .foregroundStyle(agentInboxCount > 0 ? GRColor.accent : GRColor.textSecondary)
                    // `.badge` doesn't draw on a toolbar button (checked on device), so the count is drawn here.
                    .overlay(alignment: .topTrailing) {
                        if agentInboxCount > 0 {
                            Text(agentInboxCount > 99 ? "99+" : "\(agentInboxCount)")
                                .font(.system(size: 10, weight: .bold))
                                .foregroundStyle(GRColor.canvas)
                                .padding(.horizontal, 4)
                                .padding(.vertical, 1)
                                .background(GRColor.accent, in: Capsule())
                                .offset(x: 9, y: -7)
                                .accessibilityHidden(true)
                        }
                    }
            }
            .accessibilityLabel("Agent Inbox")
            .accessibilityValue(agentInboxCount > 0 ? "\(agentInboxCount) new" : "")
            .accessibilityIdentifier("agent.inboxButton")

            Button {
                withAnimation(.easeOut(duration: 0.2)) {
                    feedStyleRaw = style == .reels ? FeedStyle.posts.rawValue : FeedStyle.reels.rawValue
                }
                GRHaptics.tap()
            } label: {
                Image(systemName: style == .reels ? "rectangle.grid.1x2" : "rectangle.portrait")
                    .foregroundStyle(GRColor.textSecondary)
            }
            .accessibilityLabel(style == .reels ? "Switch to scrolling posts" : "Switch to one card at a time")

            Button {
                router.showSearch = true
            } label: {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(GRColor.textSecondary)
            }
            .accessibilityLabel("Search")
        }
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

    private var agentInboxCount: Int {
        model.agentInsights.count + (agentBridge.isAvailable ? agentBridge.pendingCount : 0)
    }

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
