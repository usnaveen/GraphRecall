import SwiftUI

struct ContentView: View {
    @State private var tab: GRTab = ContentView.initialTab()
    @State private var openLibraryToken: Int = 0

    private static func initialTab() -> GRTab {
        guard let raw = ProcessInfo.processInfo.environment["GR_TAB"]?.lowercased() else { return .feed }
        if let match = GRTab(rawValue: raw) { return match }
        let alias: [String: GRTab] = ["today": .feed, "home": .feed, "chat": .assistant, "plus": .create]
        return alias[raw] ?? .feed
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            GRColor.canvas.ignoresSafeArea()

            Group {
                switch tab {
                case .feed: FeedView()
                case .graph: GraphView()
                case .create: CreateView()
                case .assistant: ChatView()
                case .profile: ProfileView(openLibraryToken: openLibraryToken)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            LiquidDock(selection: $tab)
        }
        .preferredColorScheme(.dark)
        .onReceive(NotificationCenter.default.publisher(for: .grNavigateLibrary)) { _ in
            tab = .profile
            openLibraryToken += 1
        }
    }
}

#Preview {
    ContentView()
}
