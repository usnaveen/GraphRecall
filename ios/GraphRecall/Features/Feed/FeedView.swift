import SwiftUI

struct FeedView: View {
    @State private var model = FeedViewModel()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top, spacing: 12) {
                    GRScreenHeader(title: "Today", subtitle: "SM-2 active recall")
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

                if model.dumpBannerCount > 0 {
                    GlassCard(cornerRadius: 14) {
                        HStack(spacing: 10) {
                            Image(systemName: "tray.and.arrow.down.fill")
                                .foregroundStyle(GRColor.accent)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("New teach cards")
                                    .font(GRType.headline)
                                    .foregroundStyle(GRColor.textPrimary)
                                Text("\(model.dumpBannerCount) from Concept Dump — graded into SM-2")
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.textSecondary)
                            }
                            Spacer()
                        }
                    }
                    .padding(.horizontal, 20)
                }

                if model.isOffline || model.pendingFlushCount > 0 {
                    offlineBanner
                        .padding(.horizontal, 20)
                }

                Group {
                    if model.isLoading && model.items.isEmpty {
                        ProgressView()
                            .tint(GRColor.accent)
                            .frame(maxWidth: .infinity, minHeight: 160)
                    } else if let item = model.currentItem {
                        reviewCard(item)
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
        .task { await model.load() }
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
                         ? "\(model.pendingFlushCount) review(s) queued for SM-2 sync"
                         : "Showing cached feed")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
                Spacer()
            }
        }
    }

    private func reviewCard(_ item: FeedItem) -> some View {
        let revealed = model.revealedIds.contains(item.id)
        return VStack(spacing: 14) {
            GlassCard {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Text(item.itemType.rawValue.replacingOccurrences(of: "_", with: " ").uppercased())
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.accent)
                        Spacer()
                        if let domain = item.domain {
                            Text(domain == "concept_dump" ? "DUMP" : domain)
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textTertiary)
                        }
                    }
                    Text(item.prompt)
                        .font(GRType.title)
                        .foregroundStyle(GRColor.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)

                    if revealed, let answer = item.answer {
                        Divider().overlay(GRColor.stroke)
                        Text(answer)
                            .font(GRType.body)
                            .foregroundStyle(GRColor.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    if revealed, let sources = item.content["sources"]?.value as? [[String: String]], !sources.isEmpty {
                        Text("Sources")
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textTertiary)
                        ForEach(Array(sources.prefix(3).enumerated()), id: \.offset) { _, src in
                            if let urlString = src["url"], let url = URL(string: urlString), !urlString.isEmpty {
                                Link(src["title"].flatMap { $0.isEmpty ? nil : $0 } ?? urlString, destination: url)
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.accentCyan)
                            }
                        }
                    }
                }
            }

            if !revealed {
                Button {
                    model.reveal(item.id)
                } label: {
                    Text("Show answer")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.canvas)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(GRColor.accent, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
            } else {
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
                Text(model.errorMessage ?? "Dump concepts in Create, or wait for the next SM-2 window.")
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)
            }
        }
    }

    private var doneState: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                Text("Session clear")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.accent)
                Text("You graded this batch. Pull to refresh for more due cards.")
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)
            }
        }
    }
}

#Preview {
    ZStack {
        GRColor.canvas.ignoresSafeArea()
        FeedView()
    }
    .preferredColorScheme(.dark)
}
