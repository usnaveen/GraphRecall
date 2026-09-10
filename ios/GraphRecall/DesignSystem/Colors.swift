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
}
