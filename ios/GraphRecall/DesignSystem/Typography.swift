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

    /// Screen titles ("Graph", "Assistant"…) in the display face chosen in Settings → Appearance
    /// (Orbitron by default). Body text stays in the system font: these faces are for headings.
    /// Falls back to the rounded system title if the chosen font isn't bundled.
    @MainActor static var screenTitle: Font { screenTitle(for: GRTitleFont.current) }

    @MainActor static func screenTitle(for choice: GRTitleFont) -> Font {
        guard let font = GRFonts.titleFont(choice, size: 30) else { return largeTitle }
        return Font(UIFontMetrics(forTextStyle: .largeTitle).scaledFont(for: font))
    }
}

/// The display faces you can pick for screen titles.
enum GRTitleFont: String, CaseIterable, Identifiable {
    case orbitron, chintzyCPU, ledLight, platinumSign, alienMushrooms, system

    var id: String { rawValue }

    var title: String {
        switch self {
        case .orbitron: return "Orbitron"
        case .chintzyCPU: return "Chintzy CPU"
        case .ledLight: return "LED Light"
        case .platinumSign: return "Platinum Sign"
        case .alienMushrooms: return "Alien Mushrooms"
        case .system: return "System"
        }
    }

    /// Asset-catalog data set and PostScript name; nil for the system font.
    var asset: (name: String, postScript: String)? {
        switch self {
        case .orbitron: return ("Orbitron", "Orbitron-Regular")
        case .chintzyCPU: return ("ChintzyCPU", "ChintzyCPUBRK")
        case .ledLight: return ("LEDLight", "LEDLIGHT")
        case .platinumSign: return ("PlatinumSign", "PlatinumSign")
        case .alienMushrooms: return ("AlienMushrooms", "AlienMushrooms")
        case .system: return nil
        }
    }

    /// Platinum Sign has capitals only.
    var uppercaseOnly: Bool { self == .platinumSign }

    /// Visual size differs a lot between these faces; this keeps titles about the same height.
    var sizeScale: CGFloat {
        switch self {
        case .chintzyCPU: return 1.15
        case .ledLight: return 1.2
        case .platinumSign: return 1.0
        case .alienMushrooms: return 1.05
        default: return 1
        }
    }

    static var current: GRTitleFont {
        GRTitleFont(rawValue: UserDefaults.standard.string(forKey: GRSettingsKey.titleFont) ?? "") ?? .orbitron
    }
}

/// Fonts that ship in the asset catalog (so no project-file entries are needed) and are registered
/// once at launch. Three of them are personal-use fonts kept out of the public repo; when one is
/// missing the title falls back to the system font.
@MainActor
enum GRFonts {
    private(set) static var isOrbitronAvailable = false
    private static var registered = false

    static func registerBundledFonts() {
        guard !registered else { return }
        registered = true
        for choice in GRTitleFont.allCases {
            guard let asset = choice.asset,
                  let data = NSDataAsset(name: asset.name)?.data,
                  let provider = CGDataProvider(data: data as CFData),
                  let font = CGFont(provider) else { continue }
            var error: Unmanaged<CFError>?
            // A second registration (e.g. previews) fails harmlessly; the font is usable either way.
            CTFontManagerRegisterGraphicsFont(font, &error)
        }
        isOrbitronAvailable = UIFont(name: "Orbitron-Regular", size: 12) != nil
    }

    static func isAvailable(_ choice: GRTitleFont) -> Bool {
        guard let asset = choice.asset else { return true }
        return UIFont(name: asset.postScript, size: 12) != nil
    }

    static func titleFont(_ choice: GRTitleFont, size: CGFloat) -> UIFont? {
        switch choice {
        case .system:
            return nil
        case .orbitron:
            return orbitron(size: size, weight: 700)
        default:
            guard let asset = choice.asset else { return nil }
            return UIFont(name: asset.postScript, size: size * choice.sizeScale)
        }
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
