import SwiftUI

/// The default feed: cards one after another, each as tall as its content (like a Reddit or
/// Instagram timeline), under the system toolbar and tab bar.
struct FeedPostsView: View {
    let model: FeedViewModel
    @Binding var dueLater: [LaterItem]
    @Environment(AppRouter.self) private var router

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                // Reminders whose time has come scroll with the feed instead of pinning over it.
                if !dueLater.isEmpty {
                    LaterDueCard(items: $dueLater)
                }
                ForEach(Array(model.queue.enumerated()), id: \.element.id) { index, item in
                    FeedContentCard(
                        item: item,
                        model: model,
                        onAsk: {
                            router.ask("Explain \(item.conceptName ?? item.title) simply.", topic: item.conceptName)
                        }
                    )
                    .onAppear {
                        Task { await model.extendQueueIfNeeded(currentIndex: index) }
                    }
                }
            }
            .padding(.horizontal, 12)
            .padding(.top, 4)
        }
        .contentMargins(.bottom, 16, for: .scrollContent)
        .scrollIndicators(.automatic)
        .accessibilityIdentifier("feed.posts")
    }
}
