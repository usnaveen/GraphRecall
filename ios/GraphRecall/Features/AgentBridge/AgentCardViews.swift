import SwiftUI

/// "From your agent" capsule shown on every agent-curated card (feed + inbox).
struct AgentProvenanceBadge: View {
    var label: String = "From your agent"
    var compact = false

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: "sparkles")
                .font(.system(size: compact ? 9 : 10, weight: .bold))
            Text(label.uppercased())
                .font(GRType.micro.weight(.bold))
                .lineLimit(1)
        }
        .foregroundStyle(GRColor.accentCyan)
        .padding(.horizontal, compact ? 7 : 9)
        .padding(.vertical, compact ? 3 : 4)
        .background(GRColor.cyanSoft, in: Capsule())
        .overlay(Capsule().stroke(GRColor.accentCyan.opacity(0.35), lineWidth: 1))
        .accessibilityElement(children: .combine)
        .accessibilityLabel(label)
        .accessibilityIdentifier("agent.badge")
    }
}

/// Source row: kind icon + the real host, tappable only for http(s) URLs.
struct AgentSourceLink: View {
    let kind: AgentSourceKind
    let url: URL?

    @Environment(\.openURL) private var openURL

    var body: some View {
        if let url {
            Button {
                openURL(url)
            } label: { label(host: AgentBridgeURL.displayHost(url)) }
            .buttonStyle(.plain)
            .accessibilityHint("Opens \(AgentBridgeURL.displayHost(url) ?? "the source") in your browser")
        } else {
            label(host: nil)
        }
    }

    private func label(host: String?) -> some View {
        HStack(spacing: 6) {
            Image(systemName: kind.systemImage)
                .font(.system(size: 11, weight: .semibold))
            Text(host ?? kind.label)
                .font(GRType.caption)
                .lineLimit(1)
            if host != nil {
                Image(systemName: "arrow.up.right")
                    .font(.system(size: 9, weight: .bold))
            }
        }
        .foregroundStyle(host != nil ? GRColor.accent : GRColor.textTertiary)
    }
}

/// Body for `FeedItemType.agentCurated` inside `FeedTypedCard`. Agent text is rendered as
/// plain `Text` (no markdown / no links) — it is untrusted input.
struct AgentCuratedCardBody: View {
    let item: FeedItem
    let revealed: Bool
    var onReveal: () -> Void = {}

    @State private var showExcerpt = false
    @State private var isIngesting = false
    @State private var didIngest = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let fc = item.agentFlashcard {
                Text(verbatim: fc.front)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                if revealed {
                    Divider().overlay(GRColor.stroke)
                    Text(verbatim: fc.back)
                        .font(.subheadline)
                        .foregroundStyle(GRColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                } else {
                    Button("Show answer", action: onReveal)
                        .grButton(.ghost, fullWidth: false, compact: true)
                }
            } else {
                if item.agentSourceKind == .substack, let author = item.substackAuthor, !author.isEmpty {
                    HStack(spacing: 6) {
                        Image(systemName: "newspaper.fill")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(GRColor.amber)
                        Text(verbatim: "By \(author)")
                            .font(GRType.caption.weight(.medium))
                            .foregroundStyle(GRColor.textTertiary)
                    }
                }

                Text(verbatim: item.title)
                    .font(.title3.weight(.bold))
                    .foregroundStyle(GRColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                if let summary = item.agentSummary {
                    Text(verbatim: summary)
                        .font(.subheadline)
                        .foregroundStyle(GRColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if !item.substackMatchedConcepts.isEmpty {
                    substackMatchedConceptsRow
                }

                if showExcerpt, let excerpt = item.substackExcerpt, !excerpt.isEmpty, excerpt != item.agentSummary {
                    Text(verbatim: excerpt)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            if let reason = item.agentReason {
                AgentReasonRow(reason: reason)
            }

            HStack(spacing: 10) {
                AgentSourceLink(kind: item.agentSourceKind, url: item.agentSourceURL)
                Spacer(minLength: 4)
                if item.agentSourceKind == .substack {
                    if let excerpt = item.substackExcerpt, !excerpt.isEmpty, excerpt != item.agentSummary {
                        Button(showExcerpt ? "Hide preview" : "Preview") {
                            withAnimation(.easeInOut(duration: 0.2)) { showExcerpt.toggle() }
                        }
                        .font(GRType.caption.weight(.semibold))
                        .foregroundStyle(GRColor.textSecondary)
                    }
                    if let url = item.agentSourceURL {
                        Button {
                            guard !isIngesting && !didIngest && !item.isSubstackIngested else { return }
                            isIngesting = true
                            Task {
                                _ = try? await APIClient.shared.ingestURL(url.absoluteString)
                                isIngesting = false
                                didIngest = true
                            }
                        } label: {
                            HStack(spacing: 5) {
                                if isIngesting {
                                    ProgressView().controlSize(.mini).tint(GRColor.canvas)
                                } else {
                                    Image(systemName: (didIngest || item.isSubstackIngested) ? "checkmark.circle.fill" : "plus.circle.fill")
                                        .font(.system(size: 11, weight: .bold))
                                }
                                Text((didIngest || item.isSubstackIngested) ? "In Graph" : "Add to Graph")
                                    .font(GRType.micro.weight(.bold))
                            }
                            .foregroundStyle((didIngest || item.isSubstackIngested) ? GRColor.accent : GRColor.canvas)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(
                                (didIngest || item.isSubstackIngested) ? GRColor.accentSoft : GRColor.accent,
                                in: Capsule()
                            )
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private var substackMatchedConceptsRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(item.substackMatchedConcepts) { match in
                    let dotColor: Color = switch match.state {
                    case "shaky": GRColor.amber
                    case "strong": GRColor.success
                    default: GRColor.accentCyan
                    }
                    HStack(spacing: 5) {
                        Circle().fill(dotColor).frame(width: 6, height: 6)
                        Text(verbatim: match.name)
                            .font(GRType.micro.weight(.semibold))
                            .foregroundStyle(GRColor.textPrimary)
                            .lineLimit(1)
                    }
                    .padding(.horizontal, 9)
                    .padding(.vertical, 5)
                    .background(GRColor.fillSubtle, in: Capsule())
                    .overlay(Capsule().stroke(dotColor.opacity(0.45), lineWidth: 1))
                }
            }
        }
    }
}

struct AgentReasonRow: View {
    let reason: String

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "lightbulb.fill")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(GRColor.amber)
                .padding(.top, 2)
            Text(verbatim: reason)
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .accessibilityLabel("Why: \(reason)")
    }
}

#if DEBUG
#Preview("Agent card in feed") {
    ZStack {
        GRColor.canvas.ignoresSafeArea()
        FeedTypedCard(item: AgentBridgeMocks.curatedFeedItem, revealed: false)
            .padding()
    }
    .preferredColorScheme(.dark)
}
#endif
