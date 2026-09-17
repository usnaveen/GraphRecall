import SwiftUI

/// One feed card, used by both feed modes: actions along the top, content in the middle at full
/// width, and the toughness slider inside the card at the bottom.
struct FeedContentCard: View {
    let item: FeedItem
    let model: FeedViewModel
    var onAsk: () -> Void
    var onGraded: () -> Void = {}

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

            FeedDifficultySlider(graded: model.grades[item.id]) { difficulty in
                Task {
                    await model.grade(item, difficulty: difficulty)
                    onGraded()
                }
            }
            .id(item.id) // a fresh slider per card
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).stroke(GRColor.stroke, lineWidth: 1))
    }

    private var topRow: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                if let name = item.conceptName, !name.isEmpty {
                    Text(name)
                        .font(GRType.caption.weight(.semibold))
                        .foregroundStyle(GRColor.textSecondary)
                        .lineLimit(1)
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
