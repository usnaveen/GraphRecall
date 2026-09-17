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
