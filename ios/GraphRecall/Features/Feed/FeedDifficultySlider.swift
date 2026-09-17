import SwiftUI

/// How hard was that card? A system slider: drag right for tougher — each band ticks under your
/// thumb, and letting go grades the card. Replaces the row of Again / Hard / Good / Easy buttons, and lives inside the
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

            // The system slider (Liquid Glass thumb); the tint follows the band under the thumb.
            Slider(value: sliderValue, in: 0...1) {
                Text("Difficulty")
            } minimumValueLabel: {
                Text("Easy")
            } maximumValueLabel: {
                Text("No idea")
            } onEditingChanged: { editing in
                if editing {
                    isScrubbing = true
                } else {
                    commit()
                }
            }
            .font(GRType.micro)
            .foregroundStyle(GRColor.textTertiary)
            .tint(activeBand.color)
            .accessibilityValue(activeBand.label)
        }
    }

    private var sliderValue: Binding<Double> {
        Binding(get: { value }, set: { update(to: $0) })
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
