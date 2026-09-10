import Foundation

enum APIConfig {
    /// Override via scheme env `GRAPHREcall_API_BASE` or edit for device LAN IP.
    static var baseURL: URL {
        if let raw = ProcessInfo.processInfo.environment["GRAPHRECALL_API_BASE"],
           let url = URL(string: raw) {
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
}
