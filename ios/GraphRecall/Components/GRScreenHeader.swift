import SwiftUI

struct GRScreenHeader: View {
    let title: String
    var subtitle: String? = nil
    /// Re-renders titles when the font is switched in Settings.
    @AppStorage(GRSettingsKey.titleFont) private var titleFontRaw = GRTitleFont.orbitron.rawValue

    private var titleFont: GRTitleFont { GRTitleFont(rawValue: titleFontRaw) ?? .orbitron }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(GRType.screenTitle(for: titleFont))
                .textCase(titleFont.uppercaseOnly ? .uppercase : nil)
                .tracking(1.5)
                .foregroundStyle(GRColor.textPrimary)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
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
