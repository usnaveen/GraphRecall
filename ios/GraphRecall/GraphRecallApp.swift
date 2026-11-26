import SwiftUI

@main
struct GraphRecallApp: App {
    init() {
        // UI-QA: `GR_TITLE_FONT=<GRTitleFont raw value>` picks the title font, as Settings would.
        if let font = ProcessInfo.processInfo.environment["GR_TITLE_FONT"], GRTitleFont(rawValue: font) != nil {
            UserDefaults.standard.set(font, forKey: GRSettingsKey.titleFont)
        }
        GRFonts.registerBundledFonts()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
