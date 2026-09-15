import SwiftUI

/// How hard was that card? Drag right for tougher — each band ticks under your thumb, and letting
/// go grades the card. Replaces the row of Again / Hard / Good / Easy buttons, and lives inside the
/// card so the content keeps the full width.
struct FeedDifficultySlider: View {
    /// Grade already recorded for this card, if any.
    var graded: ReviewDifficulty?
    var onCommit: (ReviewDifficulty) -> Void

    @State private var value: Double = 0.5
    @State private var isScrubbing = false
    @State private var lastBand: Int?

    private struct Band {
        let difficulty: ReviewDifficulty
        let label: String
        let color: Color
    }

    /// Left (easy) to right (tough).
    private static let bands: [Band] = [
        Band(difficulty: .easy, label: "Easy", color: GRColor.accent),
        Band(difficulty: .good, label: "Knew it", color: GRColor.success),
        Band(difficulty: .hard, label: "Shaky", color: GRColor.amber),
        Band(difficulty: .again, label: "No idea", color: GRColor.danger),
    ]

    private static func band(for value: Double) -> Int {
        min(bands.count - 1, max(0, Int(value * Double(bands.count))))
    }

    private var activeBand: Band {
        if let graded, let match = Self.bands.first(where: { $0.difficulty == graded }) { return match }
        return Self.bands[Self.band(for: value)]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text(graded == nil ? "How hard was it?" : "Rated")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                if graded != nil || isScrubbing {
                    Text(activeBand.label)
                        .font(GRType.micro.weight(.bold))
                        .foregroundStyle(activeBand.color)
                }
                Spacer(minLength: 0)
                if graded != nil {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 11))
                        .foregroundStyle(activeBand.color)
                }
            }

            GeometryReader { geo in
                let width = geo.size.width
                let knobX = value * width

                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(GRColor.fillSubtle)
                        .overlay(
                            Capsule().fill(
                                LinearGradient(
                                    colors: [GRColor.accent, GRColor.success, GRColor.amber, GRColor.danger],
                                    startPoint: .leading,
                                    endPoint: .trailing
                                )
                            )
                            .opacity(isScrubbing || graded != nil ? 0.85 : 0.45)
                        )
                        .overlay(Capsule().strokeBorder(GRColor.stroke, lineWidth: 1))
                        .frame(height: 22)
                        .frame(maxHeight: .infinity)

                    Circle()
                        .fill(activeBand.color)
                        .overlay(Circle().strokeBorder(.white.opacity(0.8), lineWidth: 1.5))
                        .frame(width: isScrubbing ? 26 : 22, height: isScrubbing ? 26 : 22)
                        .shadow(color: activeBand.color.opacity(0.5), radius: isScrubbing ? 7 : 3)
                        .offset(x: min(max(knobX - 11, 0), width - 22))
                        .animation(.easeOut(duration: 0.12), value: isScrubbing)
                }
                .contentShape(Rectangle())
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { drag in
                            isScrubbing = true
                            update(to: drag.location.x / max(width, 1))
                        }
                        .onEnded { _ in commit() }
                )
            }
            .frame(height: 28)

            HStack {
                Text("Easy")
                Spacer()
                Text("No idea")
            }
            .font(.system(size: 8, weight: .semibold, design: .rounded))
            .foregroundStyle(GRColor.textTertiary)
        }
        .accessibilityElement()
        .accessibilityLabel("Difficulty")
        .accessibilityValue(activeBand.label)
        .accessibilityAdjustableAction { direction in
            switch direction {
            case .increment: update(to: value + 0.25)
            case .decrement: update(to: value - 0.25)
            default: break
            }
            commit()
        }
    }

    private func update(to raw: Double) {
        let clamped = min(1, max(0, raw))
        value = clamped
        let band = Self.band(for: clamped)
        if band != lastBand {
            lastBand = band
            // Heavier tick the tougher the band, so the hand feels the scale.
            GRHaptics.tick(intensity: 0.35 + 0.2 * Double(band))
        }
    }

    private func commit() {
        isScrubbing = false
        lastBand = nil
        GRHaptics.success()
        onCommit(Self.bands[Self.band(for: value)].difficulty)
    }
}
