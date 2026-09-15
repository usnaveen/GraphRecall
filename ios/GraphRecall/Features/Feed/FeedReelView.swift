import SwiftUI

/// One card per screen, swipe up for the next. The card carries its own actions and slider, so the
/// content gets the full width.
struct FeedReelView: View {
    let model: FeedViewModel
    @Environment(AppRouter.self) private var router
    @State private var currentId: String?

    var body: some View {
        GeometryReader { geo in
            ScrollViewReader { proxy in
                ScrollView(.vertical) {
                    LazyVStack(spacing: 0) {
                        ForEach(model.queue) { item in
                            page(item, height: geo.size.height, proxy: proxy)
                                .frame(width: geo.size.width, height: geo.size.height)
                                .id(item.id)
                        }
                    }
                    .scrollTargetLayout()
                }
                .frame(height: geo.size.height) // keeps a page exactly one screen tall
                .scrollTargetBehavior(.paging)
                .scrollIndicators(.hidden)
                .scrollPosition(id: $currentId)
                .onChange(of: currentId) { _, id in
                    guard let id, let index = model.queue.firstIndex(where: { $0.id == id }) else { return }
                    model.currentIndex = index
                    Task { await model.extendQueueIfNeeded(currentIndex: index) }
                }
            }
        }
    }

    private func page(_ item: FeedItem, height: CGFloat, proxy: ScrollViewProxy) -> some View {
        VStack(spacing: 8) {
            ScrollView {
                FeedContentCard(
                    item: item,
                    model: model,
                    onAsk: {
                        router.ask("Explain \(item.conceptName ?? item.title) simply.", topic: item.conceptName)
                    },
                    onGraded: { advance(from: item.id, proxy: proxy) }
                )
                .padding(.bottom, 6)
            }
            .scrollIndicators(.hidden)

            if model.gradedIds.contains(item.id) {
                Label("Swipe up for the next one", systemImage: "chevron.up")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
            }
        }
        .padding(.horizontal, 14)
        .padding(.top, 50) // clears the floating style / search buttons
        .padding(.bottom, GRLayout.dockClearance + 6)
    }

    /// After a grade, glide to the next card so the thumb never has to.
    private func advance(from id: String, proxy: ScrollViewProxy) {
        guard let index = model.queue.firstIndex(where: { $0.id == id }), index + 1 < model.queue.count else { return }
        let nextId = model.queue[index + 1].id
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(420))
            withAnimation(.easeInOut(duration: 0.35)) {
                proxy.scrollTo(nextId, anchor: .top)
            }
        }
    }
}
