import SwiftUI

struct GlassCard<Content: View>: View {
    var cornerRadius: CGFloat = 20
    @ViewBuilder var content: () -> Content

    private var shape: RoundedRectangle {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
    }

    var body: some View {
        content()
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                if #available(iOS 26.0, *) {
                    shape
                        .fill(Color.clear)
                        .glassEffect(.regular, in: shape)
                } else {
                    shape
                        .fill(.ultraThinMaterial)
                        .overlay(shape.stroke(GRColor.strokeStrong, lineWidth: 1))
                        .shadow(color: .black.opacity(0.35), radius: 16, y: 8)
                }
            }
    }
}
