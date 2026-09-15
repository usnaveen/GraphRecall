import SwiftUI

/// The same cards as a scrolling timeline, for when one-at-a-time feels too narrow.
struct FeedPostsView: View {
    let model: FeedViewModel
    @Environment(AppRouter.self) private var router

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 22) {
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
            .padding(.horizontal, 14)
            .padding(.top, 46) // clears the floating style / search buttons
            .padding(.bottom, GRLayout.dockClearance + 16)
        }
        .scrollIndicators(.hidden)
    }
}
