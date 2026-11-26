import CoreText
import SwiftUI
import UIKit

enum GRType {
    static let largeTitle = Font.system(.largeTitle, design: .rounded).weight(.bold)
    static let title = Font.system(.title2, design: .rounded).weight(.semibold)
    static let headline = Font.system(.headline, design: .rounded)
    static let body = Font.system(.body, design: .default)
    static let caption = Font.system(.caption, design: .rounded)
    static let micro = Font.system(size: 10, weight: .medium, design: .rounded)

    /// Screen titles ("Graph", "Assistant"…): Orbitron, a wide sci-fi face (SIL OFL, ios/Licenses).
    /// Falls back to the rounded system title if the font isn't registered.
    @MainActor static var screenTitle: Font {
        guard let orbitron = GRFonts.orbitron(size: 30, weight: 700) else { return largeTitle }
        return Font(UIFontMetrics(forTextStyle: .largeTitle).scaledFont(for: orbitron))
    }
}

/// Fonts that ship in the asset catalog (so no project-file entries are needed) and are registered
/// once at launch.
@MainActor
enum GRFonts {
    private(set) static var isOrbitronAvailable = false

    static func registerBundledFonts() {
        guard !isOrbitronAvailable,
              let asset = NSDataAsset(name: "Orbitron"),
              let provider = CGDataProvider(data: asset.data as CFData),
              let font = CGFont(provider) else { return }
        var error: Unmanaged<CFError>?
        // A second registration (e.g. previews) fails harmlessly; the font is usable either way.
        CTFontManagerRegisterGraphicsFont(font, &error)
        isOrbitronAvailable = UIFont(name: "Orbitron-Regular", size: 12) != nil
    }

    /// Orbitron is a variable font; SwiftUI's `.weight` doesn't move its weight axis, so the axis
    /// ('wght', 400–900) is set on the descriptor.
    static func orbitron(size: CGFloat, weight: CGFloat) -> UIFont? {
        guard isOrbitronAvailable, let base = UIFont(name: "Orbitron-Regular", size: size) else { return nil }
        let wghtAxis = 0x7767_6874 // 'wght'
        let descriptor = base.fontDescriptor.addingAttributes([
            UIFontDescriptor.AttributeName(rawValue: kCTFontVariationAttribute as String): [wghtAxis: weight],
        ])
        return UIFont(descriptor: descriptor, size: size)
    }
}
