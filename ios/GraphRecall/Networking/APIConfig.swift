import Foundation

enum APIConfig {
    /// Override via scheme env `GRAPHREcall_API_BASE` or edit for device LAN IP.
    static var baseURL: URL {
        // UI tests run against the offline demo pack: point at a closed port so every call fails fast.
        if ProcessInfo.processInfo.environment["GR_UITEST"] != nil {
            return URL(string: "http://127.0.0.1:9")!
        }
        if let raw = ProcessInfo.processInfo.environment["GRAPHRECALL_API_BASE"],
           let url = URL(string: raw) {
            return url
        }
        // Settings → Developer → API base URL.
        if let raw = UserDefaults.standard.string(forKey: apiBaseDefaultsKey)?.trimmingCharacters(in: .whitespacesAndNewlines),
           !raw.isEmpty,
           let url = URL(string: raw), url.scheme != nil {
            return url
        }
        // Simulator → host machine localhost. Physical device needs LAN IP.
        #if targetEnvironment(simulator)
        return URL(string: "http://127.0.0.1:8000")!
        #else
        return URL(string: "http://127.0.0.1:8000")!
        #endif
    }

    static let defaultTimeout: TimeInterval = 60
    static let apiBaseDefaultsKey = "graphrecall.apiBase"
}
