import SwiftUI

enum GRColor {
    /// App canvas — matches web `#07070A`
    static let canvas = Color(red: 0.027, green: 0.027, blue: 0.039)
    /// Neon lime accent — matches web `#B6FF2E`
    static let accent = Color(red: 0.714, green: 1.0, blue: 0.180)
    /// Secondary cyan in create-button gradient — `#2EFFE6`
    static let accentCyan = Color(red: 0.180, green: 1.0, blue: 0.902)
    static let textPrimary = Color.white
    static let textSecondary = Color.white.opacity(0.60)
    static let textTertiary = Color.white.opacity(0.40)
    static let stroke = Color.white.opacity(0.12)
    static let strokeStrong = Color.white.opacity(0.18)
    static let warning = Color(red: 1.0, green: 0.72, blue: 0.30)
    static let fillSubtle = Color.white.opacity(0.06)
    static let fillMuted = Color.white.opacity(0.10)
    /// Raised surface — Figma `surface/raised` `#26262B`
    static let raised = Color(red: 0.149, green: 0.149, blue: 0.169)

    // Soft tints & lines — Figma `accent/*-soft`, `accent/lime-line`
    static let accentSoft = accent.opacity(0.18)
    static let accentLine = accent.opacity(0.40)
    static let cyanSoft = accentCyan.opacity(0.15)

    // Extended palette — web card-type / relationship colors
    static let purple = Color(red: 0.608, green: 0.349, blue: 0.714) // #9B59B6
    static let coral = Color(red: 1.0, green: 0.420, blue: 0.420)    // #FF6B6B
    static let amber = Color(red: 0.961, green: 0.620, blue: 0.043)  // #F59E0B
    static let success = Color(red: 0.204, green: 0.827, blue: 0.600) // #34D399
    static let danger = Color(red: 0.973, green: 0.443, blue: 0.443)  // #F87171
}
