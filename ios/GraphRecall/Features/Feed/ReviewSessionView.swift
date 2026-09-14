import SwiftUI
import Observation

struct SessionLaunch: Identifiable {
    let id = UUID()
    let items: [FeedItem]
}

struct GradedCard: Identifiable {
    let id = UUID()
    let item: FeedItem
    let grade: ReviewDifficulty
    let responseMs: Int
    let nextIntervalDays: Int?
}

extension ReviewDifficulty {
    /// Typical SM-2 spacing shown under each grade button before grading.
    var intervalHint: String {
        switch self {
        case .again: return "<10m"
        case .hard: return "~1d"
        case .good: return "~3d"
        case .easy: return "~7d"
        }
    }
}

extension FeedItemType {
    var systemImage: String {
        switch self {
        case .flashcard: return "rectangle.on.rectangle"
        case .mcq: return "checklist"
        case .fillBlank: return "pencil.line"
        case .showcase: return "sparkles"
        case .codeChallenge: return "chevron.left.forwardslash.chevron.right"
        case .diagram: return "point.3.connected.trianglepath.dotted"
        case .screenshot, .infographic: return "photo"
        }
    }

    var tone: GRTone {
        switch self {
        case .flashcard, .showcase: return .accent
        case .mcq, .diagram: return .purple
        case .fillBlank, .codeChallenge: return .cyan
        case .screenshot, .infographic: return .coral
        }
    }
}

extension FeedItem {
    var isOverdue: Bool {
        guard let dueDate else { return false }
        return dueDate < Calendar.current.startOfDay(for: Date())
    }
}

// MARK: - Model

@MainActor
@Observable
final class ReviewSessionModel {
    @ObservationIgnored let feed: FeedViewModel
    private(set) var queue: [FeedItem]
    private(set) var index = 0
    var revealed = false
    var selectedOptionId: String?
    var fillAnswer = ""
    var showHint = false
    private(set) var graded: [GradedCard] = []
    private(set) var isGrading = false
    var toast: String?
    private(set) var startedAt = Date()
    @ObservationIgnored private var cardStartedAt = Date()
    @ObservationIgnored private var toastTask: Task<Void, Never>?

    init(feed: FeedViewModel, items: [FeedItem]) {
        self.feed = feed
        self.queue = items
    }

    var current: FeedItem? { queue.indices.contains(index) ? queue[index] : nil }
    var isFinished: Bool { current == nil }
    var progress: Double { queue.isEmpty ? 1 : Double(index) / Double(queue.count) }
    var positionLabel: String { "Card \(min(index + 1, queue.count)) of \(queue.count)" }
    var remaining: Int { max(queue.count - index, 0) }

    func reveal() {
        revealed = true
        GRHaptics.tap()
    }

    func grade(_ difficulty: ReviewDifficulty) async {
        guard let item = current, !isGrading else { return }
        isGrading = true
        defer { isGrading = false }

        let ms = Int(Date().timeIntervalSince(cardStartedAt) * 1000)
        let result = await feed.submitGrade(for: item, difficulty: difficulty, responseTimeMs: ms)
        graded.append(GradedCard(item: item, grade: difficulty, responseMs: ms, nextIntervalDays: result?.newIntervalDays))
        if difficulty == .again { GRHaptics.warning() } else { GRHaptics.success() }
        if let days = result?.newIntervalDays {
            showToast(days <= 0 ? "Back later today" : "Next review in \(days) day\(days == 1 ? "" : "s")")
        }
        advance()
    }

    /// Moves the current card to the end of the queue.
    func skip() {
        guard let item = current, remaining > 1 else { return }
        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
            queue.remove(at: index)
            queue.append(item)
        }
        resetCard()
    }

    func restart(with items: [FeedItem]) {
        queue = items
        index = 0
        graded = []
        startedAt = Date()
        resetCard()
    }

    private func advance() {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) {
            index += 1
        }
        resetCard()
    }

    private func resetCard() {
        revealed = false
        selectedOptionId = nil
        fillAnswer = ""
        showHint = false
        cardStartedAt = Date()
    }

    private func showToast(_ message: String) {
        toast = message
        toastTask?.cancel()
        toastTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 1_800_000_000)
            guard !Task.isCancelled else { return }
            toast = nil
        }
    }

    // Summary
    var accuracy: Double {
        guard !graded.isEmpty else { return 0 }
        return Double(graded.filter { $0.grade == .good || $0.grade == .easy }.count) / Double(graded.count)
    }

    var averageSeconds: Int {
        guard !graded.isEmpty else { return 0 }
        return graded.map(\.responseMs).reduce(0, +) / graded.count / 1000
    }

    var elapsedMinutes: Int { max(1, Int(Date().timeIntervalSince(startedAt) / 60)) }

    func count(_ grade: ReviewDifficulty) -> Int { graded.filter { $0.grade == grade }.count }

    var weakCards: [GradedCard] { graded.filter { $0.grade == .again || $0.grade == .hard } }
}

// MARK: - Session view

struct ReviewSessionView: View {
    @State private var model: ReviewSessionModel
    @Environment(\.dismiss) private var dismiss
    @Environment(AppRouter.self) private var router
    private let focusLabel: String?
    private let onFinish: () -> Void

    init(feed: FeedViewModel, items: [FeedItem], focusLabel: String? = nil, onFinish: @escaping () -> Void = {}) {
        _model = State(initialValue: ReviewSessionModel(feed: feed, items: items))
        self.focusLabel = focusLabel
        self.onFinish = onFinish
    }

    var body: some View {
        ZStack {
            GRColor.canvas.ignoresSafeArea()
            GRBackdropGlow(offset: CGSize(width: 150, height: -260))

            if let item = model.current {
                session(item)
            } else {
                SessionSummaryView(
                    model: model,
                    streak: model.feed.streak,
                    onDrill: { model.restart(with: $0) },
                    onDone: close
                )
            }

            if let toast = model.toast {
                VStack {
                    Spacer()
                    GRToast(message: toast)
                        .padding(.bottom, 132)
                }
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .allowsHitTesting(false)
            }
        }
        .animation(.easeOut(duration: 0.2), value: model.toast)
        .preferredColorScheme(.dark)
    }

    private func close() {
        onFinish()
        dismiss()
    }

    private func session(_ item: FeedItem) -> some View {
        VStack(spacing: 12) {
            topBar(item)
                .padding(.horizontal, 20)
                .padding(.top, 8)

            ScrollView {
                VStack(spacing: 14) {
                    metaChips(item)

                    FeedTypedCard(
                        item: item,
                        revealed: model.revealed,
                        selectedOptionId: model.selectedOptionId,
                        fillAnswer: model.fillAnswer,
                        showHint: model.showHint,
                        onReveal: { model.reveal() },
                        onSelectOption: { model.selectedOptionId = $0 },
                        onFillAnswerChange: { model.fillAnswer = $0 },
                        onToggleHint: { model.showHint.toggle() }
                    )
                    .id(item.id)
                    .transition(.asymmetric(
                        insertion: .move(edge: .trailing).combined(with: .opacity),
                        removal: .move(edge: .leading).combined(with: .opacity)
                    ))

                    FeedCardActionBar(
                        item: item,
                        isLiked: model.feed.likedIds.contains(item.id),
                        isSaved: model.feed.savedIds.contains(item.id),
                        onLike: { Task { await model.feed.toggleLike(for: item) } },
                        onSave: { Task { await model.feed.toggleSave(for: item) } }
                    )
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 12)
            }

            VStack(spacing: 10) {
                if model.revealed {
                    gradeRow
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                secondaryActions(item)
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
            .animation(.spring(response: 0.35, dampingFraction: 0.85), value: model.revealed)
        }
    }

    private func topBar(_ item: FeedItem) -> some View {
        HStack(spacing: 12) {
            GRIconButton(systemImage: "xmark", style: .plain, tint: GRColor.textPrimary, accessibilityLabel: "End session") {
                close()
            }
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(model.positionLabel)
                        .font(GRType.caption.weight(.bold))
                        .foregroundStyle(GRColor.textPrimary)
                    Spacer()
                    if let focusLabel {
                        Text(focusLabel)
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.accent)
                    }
                }
                GRProgressBar(value: model.progress)
            }
            Menu {
                Button {
                    model.skip()
                } label: {
                    Label("Skip for now", systemImage: "arrow.uturn.forward")
                }
                .disabled(model.remaining <= 1)
                ShareLink(item: item.sharePlainText) {
                    Label("Share card", systemImage: "square.and.arrow.up")
                }
            } label: {
                Image(systemName: "ellipsis")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(GRColor.textPrimary)
                    .frame(width: 40, height: 40)
                    .background(Circle().fill(GRColor.fillSubtle))
            }
            .accessibilityLabel("More")
        }
    }

    private func metaChips(_ item: FeedItem) -> some View {
        HStack(spacing: 8) {
            if let concept = item.conceptName, !concept.isEmpty {
                GRChip(title: concept, style: .tinted(.accent), compact: true)
            }
            if let domain = item.domain, !domain.isEmpty, domain != item.conceptName {
                GRChip(title: domain == "concept_dump" ? "Concept dump" : domain, compact: true)
            }
            if item.isOverdue {
                GRChip(title: "Overdue", systemImage: "clock", style: .tinted(.warning), compact: true)
            }
            Spacer(minLength: 0)
        }
    }

    private var gradeRow: some View {
        VStack(spacing: 8) {
            Text("How well did you know it?")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textTertiary)
            HStack(spacing: 8) {
                ForEach(ReviewDifficulty.allCases) { grade in
                    Button {
                        Task { await model.grade(grade) }
                    } label: {
                        gradeLabel(grade)
                    }
                    .buttonStyle(.plain)
                    .disabled(model.isGrading)
                }
            }
        }
    }

    private func gradeLabel(_ grade: ReviewDifficulty) -> some View {
        let strong = grade == .good || grade == .easy
        let foreground: Color = strong ? GRColor.canvas : (grade == .again ? GRColor.danger : GRColor.textPrimary)
        let background: Color = strong ? GRColor.accent : (grade == .again ? GRColor.danger.opacity(0.15) : GRColor.fillMuted)
        return VStack(spacing: 1) {
            Text(grade.label)
                .font(GRType.caption.weight(.bold))
            Text(grade.intervalHint)
                .font(GRType.micro)
                .opacity(strong ? 0.65 : 0.6)
        }
        .foregroundStyle(foreground)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
        .background(background, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(GRColor.stroke, lineWidth: 1))
        .accessibilityLabel("\(grade.label), next review \(grade.intervalHint)")
    }

    private func secondaryActions(_ item: FeedItem) -> some View {
        HStack(spacing: 8) {
            GRChip(title: "Explain more", systemImage: "sparkles", style: .outline, compact: true) {
                let topic = item.conceptName ?? item.title
                router.ask("Explain this so I remember it: \(item.prompt)", topic: topic)
                close()
            }
            if let concept = item.conceptName, !concept.isEmpty {
                GRChip(title: "Open in graph", systemImage: "point.3.connected.trianglepath.dotted", style: .outline, compact: true) {
                    router.focusInGraph(item.conceptId ?? concept)
                    close()
                }
            }
            if model.remaining > 1 {
                GRChip(title: "Skip", systemImage: "arrow.uturn.forward", style: .outline, compact: true) {
                    model.skip()
                }
            }
        }
    }
}

// MARK: - Summary

struct SessionSummaryView: View {
    let model: ReviewSessionModel
    let streak: Int
    let onDrill: ([FeedItem]) -> Void
    let onDone: () -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                GRProgressRing(progress: model.graded.isEmpty ? 0 : 1, lineWidth: 10) {
                    VStack(spacing: 4) {
                        Image(systemName: model.graded.isEmpty ? "tray" : "checkmark")
                            .font(.system(size: 34, weight: .bold))
                            .foregroundStyle(GRColor.accent)
                        Text("\(model.graded.count) cards")
                            .font(GRType.headline)
                            .foregroundStyle(GRColor.textPrimary)
                    }
                }
                .frame(width: 150, height: 150)
                .background(Circle().fill(GRColor.accent.opacity(0.10)).blur(radius: 30))
                .padding(.top, 48)

                Text(model.graded.isEmpty ? "Nothing to review" : "Session complete")
                    .font(GRType.largeTitle)
                    .foregroundStyle(GRColor.textPrimary)
                Text(model.graded.isEmpty
                     ? "Add concepts in Create to fill your queue."
                     : "\(model.elapsedMinutes) min · \(streak)-day streak")
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)

                if !model.graded.isEmpty {
                    HStack(spacing: 10) {
                        GRStatChip(title: "Accuracy", value: "\(Int((model.accuracy * 100).rounded()))%", valueColor: GRColor.accent)
                        GRStatChip(title: "Avg / card", value: "\(model.averageSeconds)s", valueColor: GRColor.accent)
                        GRStatChip(title: "Missed", value: "\(model.count(.again))", valueColor: GRColor.accent)
                    }

                    breakdown

                    if !model.weakCards.isEmpty {
                        VStack(alignment: .leading, spacing: 10) {
                            GRSectionHeader(title: "Needs attention")
                            ForEach(model.weakCards) { card in
                                GRListRow(
                                    title: card.item.prompt,
                                    subtitle: card.grade == .again ? "Missed · resurfaces soon" : "Marked hard",
                                    meta: card.grade.label,
                                    metaColor: card.grade == .again ? GRColor.danger : GRColor.amber,
                                    systemImage: card.grade == .again ? "exclamationmark.triangle.fill" : "clock",
                                    tone: card.grade == .again ? .danger : .amber,
                                    showsChevron: false
                                )
                            }
                        }

                        Button {
                            onDrill(model.weakCards.map(\.item))
                        } label: {
                            Label("Drill \(model.weakCards.count) weak card\(model.weakCards.count == 1 ? "" : "s") now", systemImage: "target")
                        }
                        .buttonStyle(.grPrimary)
                    }
                }

                Button {
                    onDone()
                } label: {
                    Label("Back to Today", systemImage: "house")
                }
                .buttonStyle(model.weakCards.isEmpty ? GRButtonStyle(kind: .primary) : GRButtonStyle(kind: .secondary))
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 32)
        }
        .onAppear {
            if !model.graded.isEmpty { GRHaptics.success() }
        }
    }

    private var breakdown: some View {
        let grades: [(ReviewDifficulty, Color)] = [
            (.again, GRColor.danger), (.hard, GRColor.textTertiary), (.good, GRColor.accent), (.easy, GRColor.accentCyan)
        ]
        let total = max(model.graded.count, 1)
        return GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                Text("Grade breakdown")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                GeometryReader { geo in
                    HStack(spacing: 3) {
                        ForEach(grades, id: \.0) { grade, color in
                            let n = model.count(grade)
                            if n > 0 {
                                Rectangle()
                                    .fill(color)
                                    .frame(width: max(4, (geo.size.width - 9) * CGFloat(n) / CGFloat(total)))
                            }
                        }
                    }
                }
                .frame(height: 12)
                .clipShape(Capsule())
                HStack(spacing: 14) {
                    ForEach(grades, id: \.0) { grade, color in
                        HStack(spacing: 5) {
                            Circle().fill(color).frame(width: 8, height: 8)
                            Text("\(grade.label) \(model.count(grade))")
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textSecondary)
                        }
                    }
                }
            }
        }
    }
}
