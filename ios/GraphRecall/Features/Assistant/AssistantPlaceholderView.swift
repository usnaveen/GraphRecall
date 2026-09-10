import SwiftUI

struct AssistantPlaceholderView: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Assistant")
                    .font(GRType.largeTitle)
                    .foregroundStyle(GRColor.textPrimary)
                Text("Owned by coder slice — wire to API next.")
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)
                GlassCard {
                    Text("Liquid Glass card surface")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.accent)
                }
            }
            .padding(20)
            .padding(.bottom, 100)
        }
    }
}
