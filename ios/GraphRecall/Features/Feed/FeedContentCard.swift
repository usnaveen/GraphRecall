import SwiftUI

/// One feed card, used by both feed modes: actions along the top, content in the middle at full
/// width, and the toughness slider inside the card at the bottom.
struct FeedContentCard: View {
    private enum DigestState {
        case idle, queueing, queued
    }

    let item: FeedItem
    let model: FeedViewModel
    var onAsk: () -> Void
    var onGraded: () -> Void = {}

    @State private var digestState: DigestState = .idle

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            topRow

            FeedTypedCard(
                item: item,
                revealed: model.revealedIds.contains(item.id),
                selectedOptionId: model.selectedOptionIds[item.id],
                fillAnswer: model.fillAnswers[item.id] ?? "",
                showHint: model.hintIds.contains(item.id),
                showsContainer: false,
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

            Divider().overlay(GRColor.stroke)

            if item.isAgentCurated {
                // Agent cards are reading suggestions, not SM-2 cards: no toughness slider.
                // TODO(agent-bridge-ios): POST a seen/dismiss interaction once the backend has one.
                HStack(alignment: .center, spacing: 8) {
                    Text("Approved by you")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 4)
                    digestChip
                    GRChip(title: "Done", systemImage: "checkmark", style: .outline, compact: true) {
                        onGraded()
                    }
                }
            } else {
                FeedDifficultySlider(graded: model.grades[item.id]) { difficulty in
                    Task {
                        await model.grade(item, difficulty: difficulty)
                        onGraded()
                    }
                }
                .id(item.id) // a fresh slider per card
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).stroke(GRColor.stroke, lineWidth: 1))
        .onChange(of: item.id) { _, _ in
            digestState = .idle
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

    private var topRow: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                if let name = item.conceptName, !name.isEmpty {
                    Text(name)
                        .font(GRType.caption.weight(.semibold))
                        .foregroundStyle(GRColor.textSecondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if model.isRevisit(item) {
                    Text("REVISIT")
                        .font(.system(size: 9, weight: .bold, design: .rounded))
                        .foregroundStyle(GRColor.accentCyan)
                }
            }

            Spacer(minLength: 0)

            actionButton(
                systemName: model.savedIds.contains(item.id) ? "bookmark.fill" : "bookmark",
                active: model.savedIds.contains(item.id),
                label: "Save"
            ) {
                Task { await model.toggleSave(for: item) }
            }
            actionButton(systemName: "sparkles", active: false, label: "Ask about this", action: onAsk)
            ShareLink(item: item.sharePlainText) {
                Image(systemName: "square.and.arrow.up")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(GRColor.textSecondary)
                    .frame(width: 18, height: 18)
            }
            .buttonStyle(.glass)
            .buttonBorderShape(.circle)
            .accessibilityLabel("Share card")
        }
    }

    private func actionButton(systemName: String, active: Bool, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(active ? GRColor.accent : GRColor.textSecondary)
                .frame(width: 18, height: 18)
        }
        .buttonStyle(.glass)
        .buttonBorderShape(.circle)
        .accessibilityLabel(label)
    }
}
