import SwiftUI

struct ContentView: View {
    @State private var router = AppRouter(initialTab: ContentView.initialTab())
    @AppStorage(GRSettingsKey.hasOnboarded) private var hasOnboarded = false
    @Environment(\.scenePhase) private var scenePhase

    /// UI-QA launches with `GR_TAB` set; skip the welcome screen there.
    private var showsWelcome: Binding<Bool> {
        Binding(
            get: { !hasOnboarded && ProcessInfo.processInfo.environment["GR_TAB"] == nil && ProcessInfo.processInfo.environment["GR_SELECT"] == nil },
            set: { if !$0 { hasOnboarded = true } }
        )
    }

    private static func initialTab() -> GRTab {
        guard let raw = ProcessInfo.processInfo.environment["GR_TAB"]?.lowercased() else { return .feed }
        if let match = GRTab(rawValue: raw) { return match }
        let alias: [String: GRTab] = ["today": .feed, "home": .feed, "chat": .assistant, "plus": .create]
        return alias[raw] ?? .feed
    }

    @ViewBuilder
    private func screen(for tab: GRTab) -> some View {
        switch tab {
        case .feed: FeedView()
        case .graph: GraphView()
        case .create: CreateView()
        case .assistant: ChatView()
        case .profile: ProfileView(openLibraryToken: router.openLibraryToken)
        }
    }

    var body: some View {
        @Bindable var bindableRouter = router

        // The system tab bar: real Liquid Glass, minimises on scroll, gets out of the keyboard's way.
        // Create uses the search role so the system draws it as its own glass circle beside the bar.
        TabView(selection: $bindableRouter.tab) {
            ForEach(GRTab.allCases) { tab in
                Tab(value: tab, role: tab == .create ? .search : nil) {
                    screen(for: tab)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(GRColor.canvas.ignoresSafeArea())
                } label: {
                    Label(tab.title, systemImage: tab.systemImage)
                }
            }
        }
        .tint(GRColor.accent)
        .tabBarMinimizeBehavior(.onScrollDown)
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { _ in
            withAnimation(.easeOut(duration: 0.2)) { router.isKeyboardVisible = true }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in
            withAnimation(.easeOut(duration: 0.2)) { router.isKeyboardVisible = false }
        }
        .environment(router)
        .preferredColorScheme(.dark)
        .fullScreenCover(isPresented: showsWelcome) {
            WelcomeView { hasOnboarded = true }
        }
        .sheet(isPresented: $bindableRouter.showSearch) {
            GlobalSearchView()
                .environment(router)
                .presentationDragIndicator(.visible)
        }
        .onReceive(NotificationCenter.default.publisher(for: .grNavigateLibrary)) { _ in
            router.tab = .profile
            router.openLibraryToken += 1
        }
        .onReceive(NotificationCenter.default.publisher(for: .grNavigateFeed)) { _ in
            router.tab = .feed
        }
        .task {
            await AuthSession.shared.restore()
            // Tabs may have loaded before the token was restored.
            if AuthSession.shared.isSignedIn {
                NotificationCenter.default.post(name: .grFeedShouldReload, object: nil)
            }
        }
        .onOpenURL { url in
            if AuthSession.shared.handle(url) { return }
            router.handleDeepLink(url)
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            Task { await AuthSession.shared.refreshIfNeeded() }
        }
    }
}

#Preview {
    ContentView()
}
