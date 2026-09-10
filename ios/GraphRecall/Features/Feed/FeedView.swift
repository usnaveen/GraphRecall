import SwiftUI

struct FeedView: View {
    @State private var model = FeedViewModel()
    @State private var contentReady = false

    var body: some View {
        ZStack {
            GRColor.canvas.ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .top, spacing: 12) {
                        GRScreenHeader(
                            title: "Today",
                            subtitle: model.isDemoMode ? "Demo teach cards" : "Cards due for review"
                        )
                        Button {
                            Task { await model.load() }
                        } label: {
                            Image(systemName: "arrow.clockwise")
                                .foregroundStyle(GRColor.accent)
                                .padding(10)
                                .grGlassEffect(.interactive, in: Circle())
                        }
                        .padding(.trailing, 20)
                        .padding(.top, 12)
                    }

                    statsRow
                        .padding(.horizontal, 20)

                    if model.isDemoMode {
                        demoBanner
                            .padding(.horizontal, 20)
                    }

                    if model.dumpBannerCount > 0 {
                        GlassCard(cornerRadius: 14) {
                            HStack(spacing: 10) {
                                Image(systemName: "tray.and.arrow.down.fill")
                                    .foregroundStyle(GRColor.accent)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("New teach cards")
                                        .font(GRType.headline)
                                        .foregroundStyle(GRColor.textPrimary)
                                    Text("\(model.dumpBannerCount) new cards ready to review")
                                        .font(GRType.caption)
                                        .foregroundStyle(GRColor.textSecondary)
                                }
                                Spacer()
                            }
                        }
                        .padding(.horizontal, 20)
                    }

                    if (model.isOffline || model.pendingFlushCount > 0) && !model.isDemoMode {
                        offlineBanner
                            .padding(.horizontal, 20)
                    }

                    Group {
                        if model.isLoading && model.items.isEmpty {
                            ProgressView()
                                .tint(GRColor.accent)
                                .frame(maxWidth: .infinity, minHeight: 160)
                        } else if let item = model.currentItem {
                            reviewSession(item)
                        } else if model.items.isEmpty {
                            emptyState
                        } else {
                            doneState
                        }
                    }
                    .padding(.horizontal, 20)
                }
                .padding(.bottom, GRLayout.dockClearance)
            }
            .opacity(contentReady ? 1 : 0)
            .animation(.easeOut(duration: 0.18), value: contentReady)

            if let banner = model.softBanner {
                VStack {
                    Spacer()
                    softBannerChip(banner)
                        .padding(.horizontal, 24)
                        .padding(.bottom, GRLayout.dockClearance + 8)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                .animation(.spring(response: 0.35, dampingFraction: 0.85), value: model.softBanner)
                .allowsHitTesting(true)
                .onTapGesture { model.dismissSoftBanner() }
            }
        }
        .task {
            await model.load()
            contentReady = true
        }
        .refreshable { await model.load() }
        .onReceive(NotificationCenter.default.publisher(for: .grDumpCompleted)) { _ in
            Task { await model.load() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .grFeedShouldReload)) { _ in
            Task { await model.load() }
        }
    }

    private var statsRow: some View {
        HStack(spacing: 10) {
            statChip(title: "Due", value: "\(model.dueTotal)")
            statChip(title: "Done", value: model.progressLabel)
            statChip(title: "Streak", value: "\(model.streak)d")
        }
    }

    private func statChip(title: String, value: String) -> some View {
        GlassCard(cornerRadius: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textTertiary)
                Text(value)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.accent)
            }
        }
    }

    private var demoBanner: some View {
        GlassCard(cornerRadius: 14) {
            HStack(spacing: 10) {
                Image(systemName: "sparkles")
                    .foregroundStyle(GRColor.warning)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Demo mode")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Text(model.errorMessage ?? "Sample teach cards for Simulator / offline demos. Grades stay local.")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
                Spacer()
            }
        }
    }

    private var offlineBanner: some View {
        GlassCard(cornerRadius: 14) {
            HStack(spacing: 10) {
                Image(systemName: model.isOffline ? "wifi.slash" : "arrow.triangle.2.circlepath")
                    .foregroundStyle(GRColor.accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.isOffline ? "Offline mode" : "Syncing reviews")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Text(model.pendingFlushCount > 0
                         ? "\(model.pendingFlushCount) review(s) waiting to sync"
                         : "Showing cached cards — stats may be stale")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
                Spacer()
            }
        }
    }

    private func reviewSession(_ item: FeedItem) -> some View {
        let revealed = model.revealedIds.contains(item.id)
        return VStack(spacing: 14) {
            FeedTypedCard(
                item: item,
                revealed: revealed,
                selectedOptionId: model.selectedOptionIds[item.id],
                fillAnswer: model.fillAnswers[item.id] ?? "",
                showHint: model.hintIds.contains(item.id),
                onReveal: { model.reveal(item.id) },
                onSelectOption: { model.selectOption(itemId: item.id, optionId: $0) },
                onFillAnswerChange: { model.setFillAnswer(itemId: item.id, text: $0) },
                onToggleHint: { model.toggleHint(item.id) }
            )

            FeedCardActionBar(
                item: item,
                isLiked: model.likedIds.contains(item.id),
                isSaved: model.savedIds.contains(item.id),
                onLike: { Task { await model.toggleLike(for: item) } },
                onSave: { Task { await model.toggleSave(for: item) } }
            )

            if revealed {
                HStack(spacing: 8) {
                    ForEach(ReviewDifficulty.allCases) { grade in
                        Button {
                            Task { await model.grade(grade) }
                        } label: {
                            Text(grade.label)
                                .font(GRType.caption.weight(.semibold))
                                .foregroundStyle(grade == .good || grade == .easy ? GRColor.canvas : GRColor.textPrimary)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(
                                    (grade == .good || grade == .easy ? GRColor.accent : Color.white.opacity(0.08)),
                                    in: RoundedRectangle(cornerRadius: 16, style: .continuous)
                                )
                                .overlay(
                                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                                        .stroke(GRColor.stroke, lineWidth: 1)
                                )
                        }
                    }
                }
            }
        }
    }

    private var emptyState: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                Text("Nothing due")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.accent)
                Text(model.errorMessage ?? "Dump concepts in Create, or check back when cards are due.")
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)
            }
        }
    }

    private var doneState: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                Text(model.isDemoMode ? "Demo pack complete" : "Session clear")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.accent)
                Text(model.isDemoMode
                     ? "You walked through the sample teach cards. Pull to refresh when the API is up."
                     : "You graded this batch. Pull to refresh for more due cards.")
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)
            }
        }
    }

    private func softBannerChip(_ message: String) -> some View {
        let isError = message.localizedCaseInsensitiveContains("can\u{2019}t")
            || message.localizedCaseInsensitiveContains("couldn\u{2019}t")
            || message.localizedCaseInsensitiveContains("sign in")
            || message.localizedCaseInsensitiveContains("failed")
            || message.localizedCaseInsensitiveContains("not found")
        return HStack(spacing: 8) {
            Image(systemName: isError ? "exclamationmark.circle.fill" : "checkmark.circle.fill")
                .foregroundStyle(isError ? GRColor.textPrimary : GRColor.canvas)
            Text(message)
                .font(GRType.caption.weight(.semibold))
                .foregroundStyle(isError ? GRColor.textPrimary : GRColor.canvas)
                .lineLimit(2)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(
            (isError ? Color.white.opacity(0.14) : GRColor.accent.opacity(0.92)),
            in: Capsule()
        )
        .overlay(Capsule().stroke(GRColor.stroke, lineWidth: isError ? 1 : 0))
        .shadow(color: (isError ? Color.black.opacity(0.35) : GRColor.accent.opacity(0.25)), radius: 12, y: 4)
    }
}

#Preview {
    FeedView()
        .preferredColorScheme(.dark)
}
