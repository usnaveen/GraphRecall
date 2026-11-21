import Foundation

enum APIConfig {
    /// Override via scheme env `GRAPHRECALL_API_BASE` in Debug, Settings override in Debug,
    /// or `GRAPIBaseURL` (`GR_API_BASE_URL` in xcconfig) for Release builds.
    static var baseURL: URL {
        #if DEBUG
        // UI tests run against the offline demo pack: point at a closed port so every call fails fast.
        if ProcessInfo.processInfo.environment["GR_UITEST"] != nil {
            return URL(string: "http://127.0.0.1:9")!
        }
        if let raw = ProcessInfo.processInfo.environment["GRAPHRECALL_API_BASE"],
           let url = URL(string: raw), url.scheme != nil {
            return url
        }
        // Settings -> Developer -> API base URL.
        if let raw = UserDefaults.standard.string(forKey: apiBaseDefaultsKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !raw.isEmpty,
           let url = URL(string: raw), url.scheme != nil {
            return url
        }
        if let raw = Bundle.main.object(forInfoDictionaryKey: "GRAPIBaseURL") as? String {
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty, let url = URL(string: trimmed), url.scheme != nil {
                return url
            }
        }
        return URL(string: "http://127.0.0.1:8000")!
        #else
        if let raw = Bundle.main.object(forInfoDictionaryKey: "GRAPIBaseURL") as? String {
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if let url = URL(string: trimmed), url.scheme?.lowercased() == "https", url.host != nil {
                return url
            }
        }
        // Fallback sentinel; Release builds should configure GR_API_BASE_URL in Release.local.xcconfig.
        return URL(string: "https://api.graphrecall.invalid")!
        #endif
    }

    static var privacyPolicyURL: URL? {
        guard let raw = Bundle.main.object(forInfoDictionaryKey: "GRPrivacyPolicyURL") as? String else {
            return nil
        }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let url = URL(string: trimmed), url.scheme?.lowercased() == "https" else {
            return nil
        }
        return url
    }

    static let defaultTimeout: TimeInterval = 60
    static let apiBaseDefaultsKey = "graphrecall.apiBase"
}
