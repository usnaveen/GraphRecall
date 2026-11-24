import SwiftUI
import UIKit

/// Renders agent markdown as inline-only `AttributedString` and strips every link that is
/// not http(s) (`javascript:`, `data:`, `file:`, custom schemes…). Agent output is untrusted.
enum AgentMarkdown {
    static func render(_ text: String) -> AttributedString {
        var attributed = (try? AttributedString(
            markdown: text,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(text)
        for run in attributed.runs {
            guard let link = run.link else { continue }
            if AgentBridgeURL.safe(link.absoluteString) == nil {
                attributed[run.range].link = nil
            }
        }
        return attributed
    }
}

/// Chat section listing every hand-off in this conversation.
struct AgentAskSection: View {
    let store: AgentAskStore

    var body: some View {
        ForEach(store.tracked) { t in
            AgentAnswerBubble(
                tracked: t,
                clientTimeoutMinutes: Int(store.clientTimeout / 60),
                onRefresh: { store.refresh(t.id) },
                onCancel: { store.cancel(t.id) },
                onDismiss: { store.dismiss(t.id) }
            )
            .id("agent-\(t.id)")
        }
    }
}

struct AgentAnswerBubble: View {
    let tracked: AgentAskStore.Tracked
    var clientTimeoutMinutes = 15
    var onRefresh: () -> Void = {}
    var onCancel: () -> Void = {}
    var onDismiss: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                AgentProvenanceBadge(label: "Your agent", compact: true)
                Text(statusLine)
                    .font(GRType.caption)
                    .foregroundStyle(statusColor)
                    .lineLimit(1)
                Spacer(minLength: 0)
                if tracked.isActive {
                    ProgressView().controlSize(.mini).tint(GRColor.accentCyan)
                }
            }

            if !tracked.question.isEmpty {
                Text(verbatim: tracked.question)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textTertiary)
                    .lineLimit(3)
            }

            content

            actions
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .stroke(GRColor.accentCyan.opacity(0.25), lineWidth: 1)
        )
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("agent.answerBubble")
    }

    @ViewBuilder
    private var content: some View {
        switch tracked.phase {
        case .sending, .waiting:
            Text(tracked.consecutiveErrors >= 3
                 ? "Connection is flaky \u{2014} still checking for your agent\u{2019}s answer."
                 : "This goes to your agent, which works on it in the background. Answers usually take a few minutes; you can leave this screen.")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        case .answered:
            if let answer = tracked.request?.answerText, !answer.isEmpty {
                Text(AgentMarkdown.render(answer))
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textPrimary)
                    .tint(GRColor.accent)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            let citations = tracked.request?.citations ?? []
            if !citations.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("SOURCES")
                        .font(GRType.micro.weight(.bold))
                        .foregroundStyle(GRColor.textTertiary)
                    ForEach(Array(citations.enumerated()), id: \.offset) { _, c in
                        AgentCitationRow(citation: c)
                    }
                }
            }
        case .failed(let reason), .sendFailed(let reason):
            Text(verbatim: reason)
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        case .timedOut:
            Text("No answer after \(clientTimeoutMinutes) minutes. Your agent may still be working \u{2014} check again later.")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private var actions: some View {
        HStack(spacing: 6) {
            switch tracked.phase {
            case .sending, .waiting:
                GRChip(title: "Cancel", systemImage: "xmark", style: .outline, compact: true, action: onCancel)
            case .timedOut:
                GRChip(title: "Check again", systemImage: "arrow.clockwise", style: .outline, compact: true, action: onRefresh)
                GRChip(title: "Cancel", systemImage: "xmark", style: .outline, compact: true, action: onCancel)
            case .answered:
                if let answer = tracked.request?.answerText {
                    GRChip(title: "Copy", systemImage: "doc.on.doc", style: .outline, compact: true) {
                        UIPasteboard.general.string = answer
                        GRHaptics.tap()
                    }
                }
                // TODO(agent-bridge-ios): "Make cards" from an agent answer via the existing
                // chat create-card flow (ChatViewModel.createCard) once answers live in history.
            case .failed, .sendFailed:
                EmptyView()
            }
            Spacer(minLength: 0)
            if !tracked.isActive {
                Button(action: onDismiss) {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 15))
                        .foregroundStyle(GRColor.textTertiary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Dismiss agent answer")
            }
        }
    }

    private var statusLine: String {
        switch tracked.phase {
        case .sending: return "Sending to your agent…"
        case .waiting: return (tracked.request?.status ?? .queued).label
        case .answered: return AgentRequestStatus.answered.label
        case .failed(let r) where r == "Cancelled": return "Cancelled"
        case .failed: return AgentRequestStatus.failed.label
        case .sendFailed: return "Couldn\u{2019}t reach your agent"
        case .timedOut: return "Still waiting"
        }
    }

    private var statusColor: Color {
        switch tracked.phase {
        case .answered: return GRColor.success
        case .failed, .sendFailed: return GRColor.warning
        default: return GRColor.accentCyan
        }
    }
}

struct AgentCitationRow: View {
    let citation: AgentCitation
    @Environment(\.openURL) private var openURL

    var body: some View {
        if let url = citation.safeURL {
            Button { openURL(url) } label: { row(host: AgentBridgeURL.displayHost(url)) }
                .buttonStyle(.plain)
        } else {
            row(host: nil)
        }
    }

    private func row(host: String?) -> some View {
        HStack(spacing: 6) {
            Image(systemName: host == nil ? "doc.text" : "link")
                .font(.system(size: 10, weight: .semibold))
            Text(verbatim: citation.title)
                .font(GRType.caption)
                .lineLimit(1)
            if let host {
                Text(verbatim: host)
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                    .lineLimit(1)
            }
        }
        .foregroundStyle(host == nil ? GRColor.textSecondary : GRColor.accent)
    }
}

#if DEBUG
#Preview("Agent answers (mock)") {
    ZStack {
        GRColor.canvas.ignoresSafeArea()
        ScrollView {
            VStack(spacing: 12) { AgentAskSection(store: AgentAskStore.preview()) }
                .padding()
        }
    }
    .preferredColorScheme(.dark)
}
#endif
