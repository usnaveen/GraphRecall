import SwiftUI

struct GRScreenHeader: View {
    let title: String
    var subtitle: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(GRType.largeTitle)
                .foregroundStyle(GRColor.textPrimary)
            if let subtitle, !subtitle.isEmpty {
                Text(subtitle)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textSecondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20)
        .padding(.top, 12)
        .padding(.bottom, 8)
    }
}

enum GRLayout {
    /// Standard scroll bottom inset so content clears LiquidDock.
    static let dockClearance: CGFloat = 110
}
