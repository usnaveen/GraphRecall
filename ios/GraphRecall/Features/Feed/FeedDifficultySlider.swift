import SwiftUI

/// Shared difficulty bands ordered from lowest push (hardest / Again) to highest push (easiest / Easy).
private struct GRDifficultyBand: Equatable {
    let difficulty: ReviewDifficulty
    let shortLabel: String
    let subtitle: String
    let color: Color
    let hapticIntensity: Double

    /// Bottom (0 = hardest / Again) to Top (3 = easiest / Easy): pushing higher = easier!
    static let bottomToTop: [GRDifficultyBand] = [
        GRDifficultyBand(
            difficulty: .again,
            shortLabel: "Again",
            subtitle: "No idea",
            color: GRColor.danger,
            hapticIntensity: 0.85
        ),
        GRDifficultyBand(
            difficulty: .hard,
            shortLabel: "Hard",
            subtitle: "Shaky",
            color: GRColor.amber,
            hapticIntensity: 0.65
        ),
        GRDifficultyBand(
            difficulty: .good,
            shortLabel: "Good",
            subtitle: "Got it",
            color: GRColor.success,
            hapticIntensity: 0.48
        ),
        GRDifficultyBand(
            difficulty: .easy,
            shortLabel: "Easy",
            subtitle: "Effortless",
            color: GRColor.accent,
            hapticIntensity: 0.35
        ),
    ]

    static func index(for progress: Double) -> Int {
        let clamped = min(1.0, max(0.0, progress))
        return min(bottomToTop.count - 1, max(0, Int(clamped * Double(bottomToTop.count))))
    }

    static func band(for difficulty: ReviewDifficulty) -> GRDifficultyBand {
        bottomToTop.first(where: { $0.difficulty == difficulty }) ?? bottomToTop[2]
    }
}

/// Right-rail thumb control for Reels mode:
/// Press and hold the Liquid Glass button on the right rail to slide out a vertical difficulty
/// meter — the higher you push your thumb, the easier the concept felt (`Again` at bottom ->
/// `Hard` -> `Good` -> `Easy` at top). Releasing commits the grade with stepped haptics.
struct FeedHoldGradeRail: View {
    var graded: ReviewDifficulty?
    var onCommit: (ReviewDifficulty) -> Void

    @State private var isScrubbing = ProcessInfo.processInfo.environment["GR_PREVIEW_HOLD_SLIDER"] == "1"
    /// Normalized vertical push in `0...1` (`0` = bottom / Again, `1` = top / Easy).
    @State private var pushProgress: Double = ProcessInfo.processInfo.environment["GR_PREVIEW_HOLD_SLIDER"] == "1" ? 0.82 : 0.15
    @State private var lastBandIndex: Int?
    @State private var touchBeganAt: Date?
    @State private var showTapHint = false
    @State private var hintTask: Task<Void, Never>?

    private let trackHeight: CGFloat = 216
    private let trackWidth: CGFloat = 50

    private var activeBand: GRDifficultyBand {
        if !isScrubbing, let graded {
            return GRDifficultyBand.band(for: graded)
        }
        return GRDifficultyBand.bottomToTop[GRDifficultyBand.index(for: pushProgress)]
    }

    var body: some View {
        HStack(alignment: .bottom, spacing: 10) {
            if isScrubbing {
                scrubCallout
                    .offset(y: -thumbOffsetFromBottom + 18)
                    .transition(.scale(scale: 0.88, anchor: .trailing).combined(with: .opacity))
            } else if showTapHint {
                Text("Hold & slide up — higher = easier")
                    .font(GRType.caption.weight(.semibold))
                    .foregroundStyle(GRColor.textPrimary)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .grGlassEffect(.regular, in: Capsule())
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            }

            ZStack(alignment: .bottom) {
                if isScrubbing {
                    verticalMeterTrack
                        .transition(
                            .asymmetric(
                                insertion: .scale(scale: 0.35, anchor: .bottom).combined(with: .opacity),
                                removal: .scale(scale: 0.5, anchor: .bottom).combined(with: .opacity)
                            )
                        )
                } else {
                    restingButton
                        .transition(.scale(scale: 0.9).combined(with: .opacity))
                }
            }
            .contentShape(Rectangle())
            .highPriorityGesture(holdAndSlideGesture)
        }
        .animation(.spring(response: 0.26, dampingFraction: 0.80), value: isScrubbing)
        .animation(.spring(response: 0.28, dampingFraction: 0.84), value: showTapHint)
        .accessibilityElement(children: .ignore)
        .accessibilityIdentifier("feed.holdGradeButton")
        .accessibilityLabel("Rate recall difficulty")
        .accessibilityValue(graded.map { "Rated \($0.label)" } ?? "Not rated yet. Hold and slide up for easier.")
        .accessibilityHint("Swipe up or down with VoiceOver to adjust difficulty, or double-tap to mark Good.")
        .accessibilityAction {
            let next = graded ?? .good
            GRHaptics.success()
            onCommit(next)
        }
        .accessibilityAdjustableAction { direction in
            let currentIdx = graded.map { d in
                GRDifficultyBand.bottomToTop.firstIndex(where: { $0.difficulty == d }) ?? 2
            } ?? 2
            let nextIdx: Int
            switch direction {
            case .increment:
                nextIdx = min(GRDifficultyBand.bottomToTop.count - 1, currentIdx + 1)
            case .decrement:
                nextIdx = max(0, currentIdx - 1)
            @unknown default:
                nextIdx = currentIdx
            }
            let chosen = GRDifficultyBand.bottomToTop[nextIdx]
            GRHaptics.tick(intensity: chosen.hapticIntensity)
            onCommit(chosen.difficulty)
        }
    }

    // MARK: - Subviews

    private var restingButton: some View {
        VStack(spacing: 4) {
            Image(systemName: graded == nil ? "slider.vertical.3" : "checkmark.circle.fill")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(graded == nil ? GRColor.accent : activeBand.color)
            Text(graded == nil ? "Hold" : activeBand.shortLabel)
                .font(GRType.micro.weight(.bold))
                .foregroundStyle(graded == nil ? GRColor.textSecondary : activeBand.color)
                .lineLimit(1)
        }
        .frame(width: 52, height: 58)
        .grGlassEffect(.interactive, in: Capsule())
    }

    private var verticalMeterTrack: some View {
        let fillHeight = max(36, CGFloat(pushProgress) * trackHeight)
        return ZStack(alignment: .bottom) {
            // Luminous rising fill inside the native Liquid Glass capsule
            Capsule()
                .fill(
                    LinearGradient(
                        colors: [
                            activeBand.color.opacity(0.42),
                            activeBand.color.opacity(0.16),
                        ],
                        startPoint: .bottom,
                        endPoint: .top
                    )
                )
                .frame(width: trackWidth - 8, height: min(trackHeight - 8, fillHeight))
                .padding(.bottom, 4)

            // Four subtle rung ticks (Easy at top -> Again at bottom)
            VStack(spacing: 0) {
                ForEach(Array(GRDifficultyBand.bottomToTop.reversed().enumerated()), id: \.offset) { idx, band in
                    let isCurrent = band == activeBand
                    VStack(spacing: 2) {
                        Text(band.shortLabel.prefix(1))
                            .font(.system(size: 9, weight: .bold, design: .rounded))
                            .foregroundStyle(isCurrent ? band.color : GRColor.textTertiary)
                        Capsule()
                            .fill(isCurrent ? band.color : GRColor.strokeStrong)
                            .frame(width: isCurrent ? 16 : 8, height: 2)
                    }
                    .frame(maxHeight: .infinity)
                }
            }
            .padding(.vertical, 10)

            // Thumb puck riding under the user's finger
            Circle()
                .fill(activeBand.color)
                .frame(width: 24, height: 24)
                .shadow(color: activeBand.color.opacity(0.55), radius: 8, y: 0)
                .offset(y: -thumbOffsetFromBottom)
        }
        .frame(width: trackWidth, height: trackHeight)
        .grGlassEffect(.regular, in: Capsule())
    }

    private var scrubCallout: some View {
        VStack(alignment: .trailing, spacing: 2) {
            Text(activeBand.shortLabel)
                .font(GRType.headline.weight(.bold))
                .foregroundStyle(activeBand.color)
            Text(activeBand.subtitle)
                .font(GRType.micro)
                .foregroundStyle(GRColor.textSecondary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .grGlassEffect(.regular, in: Capsule())
    }

    private var thumbOffsetFromBottom: CGFloat {
        let usable = trackHeight - 36
        return 6 + CGFloat(pushProgress) * usable
    }

    // MARK: - Gesture

    private var holdAndSlideGesture: some Gesture {
        // `.global` keeps `translation.height` invariant when the control expands from the 58pt
        // resting pill to the 216pt vertical Liquid Glass meter mid-gesture.
        DragGesture(minimumDistance: 0, coordinateSpace: .global)
            .onChanged { drag in
                let upwardPoints = -drag.translation.height
                if touchBeganAt == nil {
                    touchBeganAt = Date()
                    showTapHint = false
                    hintTask?.cancel()
                }
                let heldSeconds = Date().timeIntervalSince(touchBeganAt ?? Date())
                if !isScrubbing && (heldSeconds >= 0.12 || abs(drag.translation.height) >= 6) {
                    isScrubbing = true
                    let initial = progress(forUpwardDrag: upwardPoints)
                    updateProgress(to: initial, forceTick: true)
                } else if isScrubbing {
                    updateProgress(to: progress(forUpwardDrag: upwardPoints), forceTick: false)
                }
            }
            .onEnded { drag in
                let heldSeconds = Date().timeIntervalSince(touchBeganAt ?? Date())
                let movedPoints = hypot(drag.translation.width, drag.translation.height)
                touchBeganAt = nil

                // A quick tap (< 160 ms, < 8 pt drag) shows a friendly hint instead of
                // accidentally recording "Again" at the bottom of the scale.
                guard isScrubbing || heldSeconds >= 0.16 || movedPoints >= 8 else {
                    GRHaptics.tap()
                    triggerTapHint()
                    return
                }

                let finalProgress = progress(forUpwardDrag: -drag.translation.height)
                let chosen = GRDifficultyBand.bottomToTop[GRDifficultyBand.index(for: finalProgress)]
                isScrubbing = false
                lastBandIndex = nil
                GRHaptics.success()
                onCommit(chosen.difficulty)
            }
    }

    private func progress(forUpwardDrag upwardPoints: CGFloat) -> Double {
        // Holding at the button rest position starts in the bottom "Again" rung (~0.10);
        // pushing 175 pt upward reaches the top "Easy" rung (1.0).
        let span: CGFloat = 175
        let normalized = Double((upwardPoints + 18) / span)
        return min(1.0, max(0.0, normalized))
    }

    private func updateProgress(to clamped: Double, forceTick: Bool) {
        pushProgress = clamped
        let bandIdx = GRDifficultyBand.index(for: clamped)
        if forceTick || bandIdx != lastBandIndex {
            lastBandIndex = bandIdx
            let band = GRDifficultyBand.bottomToTop[bandIdx]
            GRHaptics.tick(intensity: band.hapticIntensity)
        }
    }

    private func triggerTapHint() {
        showTapHint = true
        hintTask?.cancel()
        hintTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(1600))
            guard !Task.isCancelled else { return }
            showTapHint = false
        }
    }
}

/// Inline horizontal slider retained for scrolling `FeedPostsView` timeline mode.
struct FeedDifficultySlider: View {
    var graded: ReviewDifficulty?
    var onCommit: (ReviewDifficulty) -> Void

    @State private var value: Double = 0.5
    @State private var isScrubbing = false
    @State private var lastBand: Int?

    private static var bands: [GRDifficultyBand] { GRDifficultyBand.bottomToTop }

    private static func band(for value: Double) -> Int {
        GRDifficultyBand.index(for: value)
    }

    private var activeBand: GRDifficultyBand {
        if let graded { return GRDifficultyBand.band(for: graded) }
        return Self.bands[Self.band(for: value)]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text(graded == nil ? "How easy was it?" : "Rated")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                if graded != nil || isScrubbing {
                    Text(activeBand.shortLabel)
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

            Slider(value: sliderValue, in: 0...1) {
                Text("Difficulty")
            } minimumValueLabel: {
                Text("Again")
            } maximumValueLabel: {
                Text("Easy")
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
            .accessibilityValue(activeBand.shortLabel)
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
            GRHaptics.tick(intensity: Self.bands[band].hapticIntensity)
        }
    }

    private func commit() {
        isScrubbing = false
        lastBand = nil
        GRHaptics.success()
        onCommit(Self.bands[Self.band(for: value)].difficulty)
    }
}
