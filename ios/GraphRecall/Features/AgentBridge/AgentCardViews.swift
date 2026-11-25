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

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            AgentProvenanceBadge(label: item.agentProvenanceLabel, compact: true)

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
                Text(verbatim: item.title)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                if let summary = item.agentSummary {
                    Text(verbatim: summary)
                        .font(.subheadline)
                        .foregroundStyle(GRColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            if let reason = item.agentReason {
                AgentReasonRow(reason: reason)
            }
            AgentSourceLink(kind: item.agentSourceKind, url: item.agentSourceURL)
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

/// Feed top-bar entry to the approval inbox, with a pending count.
struct AgentInboxButton: View {
    let pendingCount: Int
    let action: () -> Void

    var body: some View {
        GRIconButton(
            systemImage: "tray.full",
            tint: pendingCount > 0 ? GRColor.accentCyan : GRColor.textSecondary,
            size: 38,
            accessibilityLabel: pendingCount > 0
                ? "Agent suggestions, \(pendingCount) waiting"
                : "Agent suggestions",
            action: action
        )
        .overlay(alignment: .topTrailing) {
            if pendingCount > 0 {
                Text(pendingCount > 99 ? "99+" : "\(pendingCount)")
                    .font(GRType.micro.weight(.bold))
                    .foregroundStyle(GRColor.canvas)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 1)
                    .background(GRColor.accentCyan, in: Capsule())
                    .offset(x: 4, y: -4)
                    .allowsHitTesting(false)
            }
        }
        .accessibilityIdentifier("agent.inboxButton")
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

#Preview("Inbox button") {
    HStack {
        AgentInboxButton(pendingCount: 3) {}
        AgentInboxButton(pendingCount: 0) {}
    }
    .padding()
    .background(GRColor.canvas)
}
#endif
