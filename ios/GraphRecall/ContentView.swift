import SwiftUI

struct ContentView: View {
    @State private var tab: GRTab = .feed

    var body: some View {
        ZStack(alignment: .bottom) {
            GRColor.canvas.ignoresSafeArea()

            Group {
                switch tab {
                case .feed: FeedView()
                case .graph: GraphView()
                case .create: CreatePlaceholderView()
                case .assistant: ChatView()
                case .profile: ProfilePlaceholderView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            LiquidDock(selection: $tab)
        }
        .preferredColorScheme(.dark)
    }
}

#Preview {
    ContentView()
}
