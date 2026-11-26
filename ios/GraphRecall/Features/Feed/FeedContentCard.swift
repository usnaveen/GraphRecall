import SwiftUI

/// One feed card, used by both feed modes. The content sits on top; everything you do with the
/// card (save, ask, share, and grading by press-and-hold) lives in a bar pinned to its bottom edge,
/// where the thumb already is.
struct FeedContentCard: View {
    private enum DigestState {
        case idle, queueing, queued
    }

    /// Size of the press-and-hold grading button (FeedHoldGradeRail's resting pill).
    static let gradeSlot = CGSize(width: 52, height: 58)
    /// Padding inside the bottom bar; the reel uses it to line its grading overlay up with the slot.
    static let barInsets = EdgeInsets(top: 10, leading: 14, bottom: 10, trailing: 14)

    let item: FeedItem
    let model: FeedViewModel
    /// Posts list: the grading control lives inside the bar. Reel: the reel draws it over the bar's
    /// empty slot instead, outside the paging scroll view, so a vertical scrub never turns the page.
    var showsInlineDifficulty: Bool = true
    /// Reel pages pass the page's height: the card fills it and long content scrolls inside it,
    /// so the bar never leaves the bottom of the screen. Nil in the posts list (natural height).
    var fixedHeight: CGFloat? = nil
    var onAsk: () -> Void
    var onGraded: () -> Void = {}

    @State private var digestState: DigestState = .idle
    @State private var viewportHeight: CGFloat = 0
    @State private var showRemind = false
    /// The rating slider stays tucked away until you tap the rate button (or after you've rated).
    @State private var showGrade = false

    var body: some View {
        VStack(spacing: 0) {
            if fixedHeight != nil {
                ScrollView {
                    contentStack
                        .frame(minHeight: viewportHeight, alignment: .center)
                }
                .scrollIndicators(.automatic)
                .scrollBounceBehavior(.basedOnSize)
                .frame(maxHeight: .infinity)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { viewportHeight = $0 }
            } else {
                contentStack
                if gradesInline && (showGrade || model.grades[item.id] != nil) {
                    FeedDifficultySlider(graded: model.grades[item.id]) { difficulty in
                        Task {
                            await model.grade(item, difficulty: difficulty)
                            onGraded()
                        }
                    }
                    .id(item.id) // a fresh control per card
                    .padding(.horizontal, 16)
                    .padding(.bottom, 12)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }

            Divider().overlay(GRColor.stroke)
            bottomBar
        }
        .frame(maxWidth: .infinity)
        .frame(height: fixedHeight)
        // Content sits on a plain surface; Liquid Glass is for the controls floating above it
        // (toolbar, tab bar, the buttons in the bar below), as Apple's guidance has it.
        .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(GRColor.stroke, lineWidth: 1))
        .onChange(of: item.id) { _, _ in
            digestState = .idle
        }
        .sheet(isPresented: $showRemind) {
            LaterCaptureSheet(initialText: item.conceptName ?? item.title) { _ in
                model.showSoftBanner("I'll bring it back then.")
            }
            .presentationDetents([.medium, .large])
        }
    }

    /// Posts: grade with the native slider inside the card. Reels keep the hold-and-slide rail.
    private var gradesInline: Bool {
        fixedHeight == nil && item.usesRecallGrading && !item.isAgentCurated
    }

    private var contentStack: some View {
        FeedTypedCard(
            item: item,
            revealed: model.revealedIds.contains(item.id),
            selectedOptionId: model.selectedOptionIds[item.id],
            fillAnswer: model.fillAnswers[item.id] ?? "",
            showHint: model.hintIds.contains(item.id),
            showsContainer: false,
            isRevisit: model.isRevisit(item),
            onReveal: {
                model.reveal(item.id)
                GRHaptics.tap()
            },
            onSelectOption: { optionId in
                model.selectOption(itemId: item.id, optionId: optionId)
                GRHaptics.tap()
            },
            onFillAnswerChange: { model.setFillAnswer(itemId: item.id, text: $0) },
            onToggleHint: { model.toggleHint(item.id) }
        )
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var bottomBar: some View {
        HStack(spacing: 10) {
            actionButton(
                systemName: model.savedIds.contains(item.id) ? "bookmark.fill" : "bookmark",
                active: model.savedIds.contains(item.id),
                label: "Save"
            ) {
                Task { await model.toggleSave(for: item) }
            }
            actionButton(systemName: "sparkles", active: false, label: "Ask about this", action: onAsk)
            actionButton(systemName: "clock.arrow.circlepath", active: false, label: "Remind me") {
                GRHaptics.tap()
                showRemind = true
            }
            if gradesInline {
                actionButton(
                    systemName: "dial.medium",
                    active: showGrade || model.grades[item.id] != nil,
                    label: "Rate how well you knew it"
                ) {
                    GRHaptics.tap()
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.86)) { showGrade.toggle() }
                }
            }
            ShareLink(item: item.sharePlainText) {
                Image(systemName: "square.and.arrow.up")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(GRColor.textSecondary)
                    .frame(width: 22, height: 22)
            }
            .buttonStyle(.glass)
            .buttonBorderShape(.circle)
            .accessibilityLabel("Share card")

            Spacer(minLength: 4)

            trailingControl
        }
        .padding(Self.barInsets)
        .frame(minHeight: Self.gradeSlot.height + Self.barInsets.top + Self.barInsets.bottom)
    }

    @ViewBuilder
    private var trailingControl: some View {
        if item.isAgentCurated {
            // Agent cards are reading suggestions you approved, not SM-2 cards: no grading.
            digestChip
                .fixedSize()
            actionButton(systemName: "checkmark", active: false, label: "Done") { onGraded() }
        } else if item.usesRecallGrading && !gradesInline {
            if showsInlineDifficulty {
                FeedHoldGradeRail(graded: model.grades[item.id]) { difficulty in
                    Task {
                        await model.grade(item, difficulty: difficulty)
                        onGraded()
                    }
                }
                .id(item.id) // a fresh control per card
            } else {
                Color.clear.frame(width: Self.gradeSlot.width, height: Self.gradeSlot.height)
            }
        }
    }

    private var digestChip: some View {
        Button {
            guard digestState == .idle else { return }
            digestCard()
        } label: {
            HStack(spacing: 5) {
                if digestState == .queueing {
                    ProgressView()
                        .controlSize(.mini)
                        .tint(GRColor.accentCyan)
                } else {
                    Image(systemName: digestState == .queued ? "checkmark.circle.fill" : "sparkles.rectangle.stack")
                        .font(.system(size: 10, weight: .semibold))
                }
                Text(digestState == .queued ? "Queued" : "Digest This")
                    .font(GRType.caption.weight(.semibold))
                    .lineLimit(1)
            }
            .foregroundStyle(digestState == .queued ? GRColor.accent : GRColor.accentCyan)
        }
        .buttonStyle(.glass)
        .buttonBorderShape(.capsule)
        .controlSize(.small)
        .tint(digestState == .queued ? GRColor.accent : GRColor.accentCyan)
        .disabled(digestState != .idle)
        .accessibilityIdentifier("agent.digestButton")
    }

    private func digestCard() {
        GRHaptics.tap()
        digestState = .queueing
        let url = item.agentSourceURL?.absoluteString
        let title = item.stringContent("title") ?? item.conceptName ?? item.title
        let bodyText = [item.agentSummary, item.agentReason, item.prompt]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
            .joined(separator: "\n\n")
        Task {
            do {
                try await APIClient.shared.digestLaterOrUrl(
                    url: url,
                    text: bodyText.isEmpty ? title : bodyText,
                    title: title
                )
                GRHaptics.success()
                withAnimation(.easeOut(duration: 0.2)) {
                    digestState = .queued
                }
            } catch {
                GRHaptics.warning()
                withAnimation(.easeOut(duration: 0.2)) {
                    digestState = .idle
                }
                model.showSoftBanner(APIError.userFacing(error, resource: "digest"))
            }
        }
    }

    private func actionButton(systemName: String, active: Bool, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(active ? GRColor.accent : GRColor.textSecondary)
                .frame(width: 22, height: 22)
        }
        .buttonStyle(.glass)
        .buttonBorderShape(.circle)
        .accessibilityLabel(label)
    }
}
