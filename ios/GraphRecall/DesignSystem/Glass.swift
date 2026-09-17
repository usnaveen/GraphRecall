import SwiftUI

/// Native Liquid Glass helpers (iOS 26+) with material fallbacks.
struct GRGlass {
    @ViewBuilder
    static func surface<S: Shape>(in shape: S = RoundedRectangle(cornerRadius: 20, style: .continuous)) -> some View {
        if #available(iOS 26.0, *) {
            Color.clear
                .glassEffect(.regular, in: shape)
        } else {
            shape.fill(.ultraThinMaterial)
                .overlay(shape.stroke(GRColor.stroke, lineWidth: 1))
        }
    }
}

extension View {
    /// Apply Liquid Glass when available; otherwise ultra-thin material.
    @ViewBuilder
    func grGlassEffect(
        _ style: GRGlassStyle = .regular,
        in shape: some Shape = RoundedRectangle(cornerRadius: 20, style: .continuous)
    ) -> some View {
        if #available(iOS 26.0, *) {
            switch style {
            case .regular:
                self.glassEffect(.regular, in: shape)
            case .clear:
                self.glassEffect(.clear, in: shape)
            case .interactive:
                self.glassEffect(.regular.interactive(), in: shape)
            }
        } else {
            self
                .background(shape.fill(.ultraThinMaterial))
                .overlay(shape.stroke(GRColor.stroke, lineWidth: 1))
        }
    }
}

enum GRGlassStyle {
    case regular, clear, interactive
}

/// The app's one "green button" look: accent-tinted system Liquid Glass. Used for every primary
/// action — icon buttons, primary CTAs and card reveals — so nothing is flat paint.
struct GRAccentGlass<S: InsettableShape>: View {
    let shape: S
    var tint: Color = GRColor.accent
    var strength: Double = 0.42

    var body: some View {
        // System glass only — no painted highlights, strokes or shadows on top of it.
        Color.clear
            .glassEffect(.regular.tint(tint.opacity(strength)).interactive(), in: shape)
    }
}
