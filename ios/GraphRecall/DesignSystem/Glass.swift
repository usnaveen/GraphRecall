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

/// The app's one "green button" look: accent-tinted Liquid Glass with a specular highlight,
/// like light caught in a drop of water. Used for every primary action — the dock's Create
/// button, icon buttons, primary CTAs and card reveals — so nothing is flat paint.
struct GRAccentGlass<S: InsettableShape>: View {
    let shape: S
    var tint: Color = GRColor.accent
    var strength: Double = 0.42

    var body: some View {
        ZStack {
            if #available(iOS 26.0, *) {
                shape
                    .fill(
                        LinearGradient(
                            colors: [tint.opacity(0.22), GRColor.accentCyan.opacity(0.12)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .glassEffect(.regular.tint(tint.opacity(strength)).interactive(), in: shape)
            } else {
                shape
                    .fill(.ultraThinMaterial)
                    .overlay(shape.fill(tint.opacity(strength + 0.1)))
            }

            GeometryReader { geo in
                Ellipse()
                    .fill(LinearGradient(colors: [.white.opacity(0.5), .white.opacity(0)], startPoint: .top, endPoint: .bottom))
                    .frame(width: geo.size.width * 0.58, height: min(geo.size.height * 0.42, 14))
                    .position(x: geo.size.width / 2, y: min(geo.size.height * 0.26, 9))
                    .blendMode(.plusLighter)
            }
            .allowsHitTesting(false)

            shape
                .strokeBorder(
                    LinearGradient(colors: [.white.opacity(0.45), tint.opacity(0.12)], startPoint: .top, endPoint: .bottom),
                    lineWidth: 1
                )
        }
        .shadow(color: tint.opacity(0.22), radius: 6, y: 2)
    }
}
