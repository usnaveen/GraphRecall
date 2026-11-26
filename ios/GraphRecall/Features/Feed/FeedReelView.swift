import SwiftUI

/// ADHD-friendly Reels page: one focused concept card per screen, vertical paging, and a
/// thumb-reachable right-rail button that slides out a vertical Liquid Glass difficulty meter
/// when held (higher push = easier recall).
struct FeedReelView: View {
    let model: FeedViewModel
    /// Height of the floating tab bar (and home indicator). The reel runs underneath it, like
    /// Instagram or TikTok, and uses this to keep cards and the grading rail clear of it.
    var bottomInset: CGFloat = 0
    @Environment(AppRouter.self) private var router
    @State private var currentId: String?

    private var activeItem: FeedItem? {
        if let id = currentId, let match = model.queue.first(where: { $0.id == id }) {
            return match
        }
        return model.queue.first
    }

    var body: some View {
        GeometryReader { geo in
            ScrollViewReader { proxy in
                ZStack(alignment: .bottomTrailing) {
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
                    .frame(height: geo.size.height) // keeps each Reel page strictly one screen tall
                    .scrollTargetBehavior(.paging)
                    .scrollIndicators(.hidden)
                    .scrollPosition(id: $currentId)
                    .onAppear {
                        if currentId == nil {
                            currentId = model.queue.first?.id
                        }
                    }
                    .onChange(of: model.queue.first?.id) { _, firstId in
                        if let firstId, currentId == nil || !model.queue.contains(where: { $0.id == currentId }) {
                            currentId = firstId
                        }
                    }
                    .onChange(of: currentId) { _, id in
                        guard let id, let index = model.queue.firstIndex(where: { $0.id == id }) else { return }
                        model.currentIndex = index
                        Task { await model.extendQueueIfNeeded(currentIndex: index) }
                    }

                    // Press-and-hold vertical grading control. It is drawn here, over the empty slot
                    // at the right of the card's bottom bar, so it looks part of the card while staying
                    // outside the paging scroll view: a vertical scrub never turns the page.
                    // Only on active-recall cards (not showcases or revisit cards).
                    if let active = activeItem, active.usesRecallGrading {
                        FeedHoldGradeRail(graded: model.grades[active.id]) { difficulty in
                            let gradedId = active.id
                            Task {
                                await model.grade(active, difficulty: difficulty)
                                advance(from: gradedId, proxy: proxy)
                            }
                        }
                        .id(active.id)
                        .padding(.trailing, Self.sidePadding + FeedContentCard.barInsets.trailing)
                        .padding(.bottom, bottomInset + Self.bottomGap + FeedContentCard.barInsets.bottom)
                    }
                }
            }
        }
    }

    private static let topChrome: CGFloat = 50   // the floating Agent Inbox / style / search buttons
    private static let sidePadding: CGFloat = 14
    private static let bottomGap: CGFloat = 12   // between the card and the floating tab bar

    /// One page: a card exactly as tall as the screen allows. Its content scrolls inside it and
    /// its action bar stays pinned at the bottom, just above the floating tab bar.
    private func page(_ item: FeedItem, height: CGFloat, proxy: ScrollViewProxy) -> some View {
        let cardHeight = max(320, height - Self.topChrome - bottomInset - Self.bottomGap)
        return FeedContentCard(
            item: item,
            model: model,
            showsInlineDifficulty: false,
            fixedHeight: cardHeight,
            onAsk: {
                router.ask("Explain \(item.conceptName ?? item.title) simply.", topic: item.conceptName)
            },
            onGraded: { advance(from: item.id, proxy: proxy) }
        )
        .padding(.horizontal, Self.sidePadding)
        .padding(.top, Self.topChrome)
        .frame(height: height, alignment: .top)
    }

    /// After a grade, glide smoothly to the next Reel card so the thumb never has to.
    private func advance(from id: String, proxy: ScrollViewProxy) {
        guard let index = model.queue.firstIndex(where: { $0.id == id }), index + 1 < model.queue.count else { return }
        let nextId = model.queue[index + 1].id
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(360))
            withAnimation(.easeInOut(duration: 0.35)) {
                currentId = nextId
                proxy.scrollTo(nextId, anchor: .top)
            }
        }
    }
}
