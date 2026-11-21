import SwiftUI

/// Liquid Glass drawer surfacing provenance-grounded proactive insights from Agent v2.
struct AgentInsightsSheet: View {
    let model: FeedViewModel
    @Environment(\.dismiss) private var dismiss
    @Environment(AppRouter.self) private var router

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                GRBackdropGlow()

                if model.agentInsights.isEmpty {
                    emptyState
                } else {
                    ScrollView {
                        LazyVStack(spacing: 16) {
                            ForEach(model.agentInsights) { card in
                                insightCardView(card)
                            }
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                    }
                    .scrollIndicators(.hidden)
                }
            }
            .navigationTitle("Agent Inbox")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .foregroundStyle(GRColor.accent)
                }
            }
        }
    }

    private func insightCardView(_ card: AgentFeedCard) -> some View {
        let tone = toneFor(card.insightType)
        return GlassCard(cornerRadius: 22) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    GRChip(
                        title: card.typeLabel,
                        systemImage: card.typeIcon,
                        style: .tinted(tone),
                        compact: true
                    )
                    if card.isDemo {
                        GRChip(
                            title: "Demo preview",
                            style: .outline,
                            compact: true
                        )
                    }
                    Spacer()
                }

                Text(card.title)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)

                Text(card.bodyMd)
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)

                if !card.conceptIds.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            ForEach(card.conceptIds, id: \.self) { concept in
                                GRChip(title: concept, style: .plain, compact: true)
                            }
                        }
                    }
                }

                if !card.sourceQuotes.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Grounded in your notes")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                            .textCase(.uppercase)

                        ForEach(card.sourceQuotes) { q in
                            HStack(alignment: .top, spacing: 8) {
                                Rectangle()
                                    .fill(GRColor.accentLine)
                                    .frame(width: 2)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("\"\(q.quote)\"")
                                        .font(GRType.caption)
                                        .foregroundStyle(GRColor.textPrimary)
                                        .italic()
                                    Text("— \(q.noteTitle)")
                                        .font(GRType.micro)
                                        .foregroundStyle(GRColor.textTertiary)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }

                HStack(spacing: 10) {
                    Button {
                        GRHaptics.tap()
                        model.actOnInsight(card)
                        dismiss()
                        router.ask("Explore this insight: \(card.title)", topic: card.conceptIds.first)
                    } label: {
                        Label("Ask Assistant", systemImage: "sparkles")
                    }
                    .grButton(.primary, fullWidth: true, compact: true)

                    Button {
                        GRHaptics.tap()
                        model.dismissInsight(card)
                    } label: {
                        Text("Dismiss")
                    }
                    .grButton(.secondary, fullWidth: false, compact: true)
                }
            }
        }
    }

    private var emptyState: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                Label("All caught up", systemImage: "checkmark.seal.fill")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.accent)
                Text("Your always-on agent will surface verified cross-note connections and lapse prompts here.")
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)
            }
        }
        .padding(.horizontal, 20)
    }

    private func toneFor(_ insightType: String) -> GRTone {
        switch insightType.lowercased() {
        case "connection": return .cyan
        case "conflict": return .amber
        case "remedial": return .coral
        case "briefing": return .accent
        default: return .purple
        }
    }
}
