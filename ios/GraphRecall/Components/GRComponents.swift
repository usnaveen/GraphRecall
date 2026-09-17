import SwiftUI
import UIKit

// Shared controls mirroring the Figma "GraphRecall iOS — Revamp" component library
// (Button, Chip, IconButton, StatChip, Banner, SectionHeader, ListRow, ProgressBar, Toast).

// MARK: - Tone

enum GRTone: Hashable {
    case accent, cyan, purple, coral, amber, success, danger, warning, neutral

    var color: Color {
        switch self {
        case .accent: return GRColor.accent
        case .cyan: return GRColor.accentCyan
        case .purple: return GRColor.purple
        case .coral: return GRColor.coral
        case .amber: return GRColor.amber
        case .success: return GRColor.success
        case .danger: return GRColor.danger
        case .warning: return GRColor.warning
        case .neutral: return GRColor.textSecondary
        }
    }

    var soft: Color {
        self == .neutral ? GRColor.fillSubtle : color.opacity(0.16)
    }
}

// MARK: - Buttons

/// Button roles, drawn with the system Liquid Glass button styles.
enum GRButtonKind { case primary, secondary, ghost, destructive }

extension View {
    /// Native glass button: `.glassProminent` for the main action, `.glass` for the rest.
    @ViewBuilder
    func grButton(_ kind: GRButtonKind = .primary, fullWidth: Bool = true, compact: Bool = false) -> some View {
        let sized = self
            .buttonSizing(fullWidth ? .flexible : .fitted)
            .controlSize(compact ? .regular : .large)
            .buttonBorderShape(.capsule)
        switch kind {
        case .primary:
            sized.buttonStyle(.glassProminent).tint(GRColor.accent).foregroundStyle(GRColor.canvas)
        case .secondary:
            sized.buttonStyle(.glass)
        case .ghost:
            sized.buttonStyle(.glass).tint(GRColor.accent).foregroundStyle(GRColor.accent)
        case .destructive:
            sized.buttonStyle(.glass).foregroundStyle(GRColor.danger)
        }
    }
}

/// Circular icon button on the system glass button styles.
struct GRIconButton: View {
    enum Style { case glass, accent, plain }

    let systemImage: String
    var style: Style = .glass
    var tint: Color? = nil
    var size: CGFloat = 40
    let accessibilityLabel: String
    let action: () -> Void

    var body: some View {
        let button = Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: size * 0.4, weight: .semibold))
                .foregroundStyle(foreground)
                .frame(width: size * 0.6, height: size * 0.6)
        }
        .buttonBorderShape(.circle)
        .accessibilityLabel(accessibilityLabel)

        switch style {
        case .glass: button.buttonStyle(.glass)
        case .accent: button.buttonStyle(.glassProminent).tint(GRColor.accent)
        case .plain: button.buttonStyle(.borderless)
        }
    }

    private var foreground: Color {
        if let tint { return tint }
        switch style {
        case .glass: return GRColor.accent
        case .accent: return GRColor.canvas
        case .plain: return GRColor.textSecondary
        }
    }
}

// MARK: - Chip

struct GRChip: View {
    enum Style { case selected, plain, tinted(GRTone), outline }

    let title: String
    var systemImage: String? = nil
    var style: Style = .plain
    var compact = false
    var action: (() -> Void)? = nil

    var body: some View {
        if let action {
            // Tappable chips are real glass buttons; the selected one is the prominent (tinted) glass.
            let button = Button(action: action) { content }
                .controlSize(compact ? .small : .regular)
                .buttonBorderShape(.capsule)
            switch style {
            case .selected:
                button.buttonStyle(.glassProminent).tint(GRColor.accent).foregroundStyle(GRColor.canvas)
            case .tinted(let tone):
                button.buttonStyle(.glass).tint(tone.color).foregroundStyle(tone == .neutral ? GRColor.textPrimary : tone.color)
            case .plain, .outline:
                button.buttonStyle(.glass).foregroundStyle(GRColor.textPrimary)
            }
        } else {
            tag
        }
    }

    private var content: some View {
        HStack(spacing: 5) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(.system(size: compact ? 10 : 11, weight: .semibold))
            }
            Text(title)
                .font(isSelected ? GRType.caption.weight(.bold) : GRType.caption)
                .lineLimit(1)
        }
    }

    /// Non-interactive label (a tag on content, not a control).
    private var tag: some View {
        content
            .padding(.horizontal, compact ? 10 : 14)
            .padding(.vertical, compact ? 5 : 8)
            .foregroundStyle(foreground)
            .background(background, in: Capsule(style: .continuous))
            .overlay(Capsule(style: .continuous).stroke(isOutline ? GRColor.strokeStrong : .clear, lineWidth: 1))
    }

    private var isSelected: Bool { if case .selected = style { return true }; return false }
    private var isOutline: Bool { if case .outline = style { return true }; return false }

    private var foreground: Color {
        switch style {
        case .selected: return GRColor.canvas
        case .plain: return GRColor.textSecondary
        case .tinted(let tone): return tone == .neutral ? GRColor.textPrimary : tone.color
        case .outline: return GRColor.textPrimary
        }
    }

    private var background: Color {
        switch style {
        case .selected: return GRColor.accent
        case .plain: return GRColor.fillSubtle
        case .tinted(let tone): return tone.soft
        case .outline: return .clear
        }
    }
}

// MARK: - Headers, rows, stats

struct GRSectionHeader: View {
    let title: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
            Spacer()
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .font(GRType.caption.weight(.bold))
                    .buttonStyle(.borderless)
                    .tint(GRColor.accent)
            }
        }
    }
}

struct GRIconTile: View {
    let systemImage: String
    var tone: GRTone = .accent
    var size: CGFloat = 38

    var body: some View {
        Image(systemName: systemImage)
            .font(.system(size: size * 0.42, weight: .semibold))
            .foregroundStyle(tone.color)
            .frame(width: size, height: size)
            .background(tone.soft, in: RoundedRectangle(cornerRadius: size * 0.29, style: .continuous))
    }
}

struct GRListRow: View {
    let title: String
    var subtitle: String? = nil
    var meta: String? = nil
    var metaColor: Color = GRColor.textTertiary
    var systemImage: String = "circle"
    var tone: GRTone = .accent
    var showsChevron = true

    var body: some View {
        HStack(spacing: 12) {
            GRIconTile(systemImage: systemImage, tone: tone)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                if let subtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            if let meta, !meta.isEmpty {
                Text(meta)
                    .font(GRType.caption.weight(.semibold))
                    .foregroundStyle(metaColor)
                    .lineLimit(1)
            }
            if showsChevron {
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(GRColor.textTertiary)
            }
        }
        .padding(.vertical, 12)
        .padding(.leading, 12)
        .padding(.trailing, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .contentShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

struct GRStatChip: View {
    let title: String
    let value: String
    var systemImage: String? = nil
    var valueColor: Color = GRColor.textPrimary

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 4) {
                if let systemImage {
                    Image(systemName: systemImage)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(GRColor.accent)
                }
                Text(title)
                    .font(systemImage == nil ? GRType.caption : GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                    .lineLimit(1)
            }
            Text(value)
                .font(GRType.headline)
                .foregroundStyle(valueColor)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

struct GRBanner: View {
    let systemImage: String
    let title: String
    var subtitle: String? = nil
    var tone: GRTone = .accent

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(tone.color)
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                if let subtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 14)
        .padding(.horizontal, 16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

// MARK: - Progress

struct GRProgressBar: View {
    let value: Double
    var tint: Color = GRColor.accent
    var height: CGFloat = 6

    var body: some View {
        ProgressView(value: min(max(value, 0), 1))
            .progressViewStyle(.linear)
            .tint(tint)
            .animation(.easeOut(duration: 0.3), value: value)
    }
}

struct GRProgressRing<Content: View>: View {
    let progress: Double
    var lineWidth: CGFloat = 8
    var tint: Color = GRColor.accent
    @ViewBuilder var content: () -> Content

    var body: some View {
        ZStack {
            Circle().stroke(GRColor.fillMuted, lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: min(max(progress, 0), 1))
                .stroke(tint, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(.spring(response: 0.6, dampingFraction: 0.85), value: progress)
            content()
        }
        .padding(lineWidth / 2)
    }
}

// MARK: - Feedback

struct GRToast: View {
    let message: String
    var isError = false

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: isError ? "exclamationmark.triangle.fill" : "checkmark")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(isError ? GRColor.danger : GRColor.canvas)
            Text(message)
                .font(GRType.caption.weight(.bold))
                .foregroundStyle(isError ? GRColor.textPrimary : GRColor.canvas)
                .lineLimit(2)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(isError ? GRColor.raised : GRColor.accent, in: Capsule())
        .overlay(Capsule().stroke(isError ? GRColor.strokeStrong : .clear, lineWidth: 1))
        .shadow(color: .black.opacity(0.35), radius: 12, y: 4)
    }
}

struct GRCheckbox: View {
    let isOn: Bool

    /// The system selection mark (as in Mail / Photos edit mode).
    var body: some View {
        Image(systemName: isOn ? "checkmark.circle.fill" : "circle")
            .font(.system(size: 22))
            .foregroundStyle(isOn ? GRColor.accent : GRColor.textTertiary)
            .contentTransition(.symbolEffect(.replace))
            .accessibilityAddTraits(isOn ? .isSelected : [])
    }
}

enum GRHaptics {
    private static var enabled: Bool {
        UserDefaults.standard.object(forKey: GRSettingsKey.haptics) as? Bool ?? true
    }

    @MainActor static func tap() {
        guard enabled else { return }
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }

    @MainActor static func success() {
        guard enabled else { return }
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    @MainActor static func warning() {
        guard enabled else { return }
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
    }

    /// A single crisp tick — used while scrubbing the feed's difficulty slider.
    @MainActor static func tick(intensity: Double = 0.6) {
        guard enabled else { return }
        let generator = UIImpactFeedbackGenerator(style: .rigid)
        generator.prepare()
        generator.impactOccurred(intensity: max(0.15, min(1, intensity)))
    }
}

enum GRSettingsKey {
    static let haptics = "graphrecall.haptics"
    static let reviewImports = "graphrecall.reviewImports"
    static let remindersEnabled = "graphrecall.reminders.enabled"
    static let reminderMinutes = "graphrecall.reminders.minutes"
    static let hasOnboarded = "graphrecall.hasOnboarded"
    static let displayName = "graphrecall.displayName"
    /// 0 = use the server's goal.
    static let dailyGoal = "graphrecall.study.dailyGoal"
    static let newCardsPerDay = "graphrecall.study.newCardsPerDay"
    /// "reels" (one card at a time) or "posts" (scrolling timeline).
    static let feedStyle = "graphrecall.feed.style"
}

// MARK: - Layout

/// Wrapping row for chips (concept tags, parsed concepts, filters).
struct GRFlowLayout: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, lineHeight: CGFloat = 0, widest: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0, x + size.width > maxWidth {
                y += lineHeight + lineSpacing
                x = 0
                lineHeight = 0
            }
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
            widest = max(widest, x - spacing)
        }
        return CGSize(width: proposal.width ?? widest, height: y + lineHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, lineHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX {
                y += lineHeight + lineSpacing
                x = bounds.minX
                lineHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
    }
}

/// Soft lime/cyan glow used behind screen headers.
struct GRBackdropGlow: View {
    var tint: Color = GRColor.accent
    var offset: CGSize = CGSize(width: 140, height: -200)

    var body: some View {
        Circle()
            .fill(tint.opacity(0.14))
            .frame(width: 300, height: 300)
            .blur(radius: 70)
            .offset(offset)
            .allowsHitTesting(false)
    }
}
