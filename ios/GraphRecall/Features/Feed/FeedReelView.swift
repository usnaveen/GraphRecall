import SwiftUI

/// ADHD-friendly Reels page: one focused concept card per screen, vertical paging, and a
/// thumb-reachable right-rail button that slides out a vertical Liquid Glass difficulty meter
/// when held (higher push = easier recall).
struct FeedReelView: View {
    let model: FeedViewModel
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

                    // Right-rail press-and-hold vertical difficulty slider anchored above the
                    // ScrollView so vertical thumb scrubbing never fights Reel paging.
                    // Only shown on active-recall cards (not passive Showcases / Revisit cards).
                    if let active = activeItem, active.usesRecallGrading {
                        FeedHoldGradeRail(graded: model.grades[active.id]) { difficulty in
                            let gradedId = active.id
                            Task {
                                await model.grade(active, difficulty: difficulty)
                                advance(from: gradedId, proxy: proxy)
                            }
                        }
                        .id(active.id)
                        .padding(.trailing, 18)
                        .padding(.bottom, 16)
                    }
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
                    showsInlineDifficulty: false,
                    onAsk: {
                        router.ask("Explain \(item.conceptName ?? item.title) simply.", topic: item.conceptName)
                    },
                    onGraded: { advance(from: item.id, proxy: proxy) }
                )
                // Extra bottom breathing room so long card content can scroll clear of the right-rail button
                .padding(.bottom, 76)
            }
            .scrollIndicators(.hidden)

            if model.gradedIds.contains(item.id) {
                Label("Swipe up for the next one", systemImage: "chevron.up")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.leading, 8)
            }
        }
        .padding(.horizontal, 14)
        .padding(.top, 50) // clears the floating Agent Inbox / style / search chrome
        .padding(.bottom, 6)
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
