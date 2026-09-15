@preconcurrency import GoogleSignIn
import SwiftUI
import UIKit

/// Owns sign-in state: Google Sign-In when configured, otherwise the local demo token.
/// The Google ID token is the backend bearer (`backend/auth/middleware.py` verifies it per request).
@MainActor
@Observable
final class AuthSession {
    static let shared = AuthSession()

    enum State: Equatable {
        case signedOut
        case demo
        /// Docker backend with DEBUG=true, which accepts `test-token` as a test user.
        case localDev
        case google(name: String?, email: String?)
    }

    private(set) var state: State = .signedOut
    private(set) var isWorking = false
    var lastError: String?

    static let demoToken = "demo-local-token"
    private static let demoKey = "graphrecall.auth.demo"
    /// Matches `backend/auth/google_oauth.py`'s DEBUG bypass.
    static let localDevToken = "test-token"
    /// The simulator shares the Mac's network stack; a phone has to reach the Mac by its LAN or
    /// hotspot address, set as `GR_DEV_SERVER_HOST` in ios/Config/Dev.local.xcconfig.
    static var localDevBaseURL: String {
        #if targetEnvironment(simulator)
        return "http://127.0.0.1:8001"
        #else
        let host = (Bundle.main.object(forInfoDictionaryKey: "GRDevServerHost") as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return "http://\(host.isEmpty ? "127.0.0.1" : host):8001"
        #endif
    }
    private static let localDevKey = "graphrecall.auth.localDev"

    /// True once `GIDClientID` in Info.plist holds a real client ID (see ios/Config/Google.local.xcconfig.example).
    var isGoogleConfigured: Bool {
        let clientId = Bundle.main.object(forInfoDictionaryKey: "GIDClientID") as? String ?? ""
        return clientId.hasSuffix(".apps.googleusercontent.com")
    }

    var isSignedIn: Bool { state != .signedOut }

    var statusLabel: String {
        switch state {
        case .signedOut: return "Not signed in"
        case .demo: return "Demo session"
        case .localDev: return "Local Docker backend · test user"
        case .google(_, let email): return email.map { "Signed in as \($0)" } ?? "Signed in with Google"
        }
    }

    /// Restores a previous Google session (refreshing its ID token) or the demo token.
    func restore() async {
        if ProcessInfo.processInfo.environment["GR_UITEST"] != nil { return }
        if isGoogleConfigured, GIDSignIn.sharedInstance.hasPreviousSignIn() {
            do {
                let user = try await GIDSignIn.sharedInstance.restorePreviousSignIn()
                try await adopt(user, registerWithBackend: false)
                return
            } catch {
                lastError = "Your Google session expired — sign in again."
            }
        }
        if UserDefaults.standard.bool(forKey: Self.localDevKey) {
            await APIClient.shared.setAccessToken(Self.localDevToken)
            state = .localDev
            return
        }
        if UserDefaults.standard.bool(forKey: Self.demoKey) {
            await APIClient.shared.setAccessToken(Self.demoToken)
            state = .demo
        }
    }

    /// Points the app at `docker compose up` on this Mac and signs in as the backend's test user.
    func useLocalDevSession() async {
        lastError = nil
        UserDefaults.standard.set(Self.localDevBaseURL, forKey: APIConfig.apiBaseDefaultsKey)
        UserDefaults.standard.set(true, forKey: Self.localDevKey)
        UserDefaults.standard.set(false, forKey: Self.demoKey)
        await APIClient.shared.setAccessToken(Self.localDevToken)
        state = .localDev
    }

    /// Google ID tokens last an hour; call when the app returns to the foreground.
    func refreshIfNeeded() async {
        guard case .google = state, let user = GIDSignIn.sharedInstance.currentUser else { return }
        try? await adopt(user, registerWithBackend: false)
    }

    func signInWithGoogle() async {
        lastError = nil
        guard isGoogleConfigured else {
            lastError = "Google Sign-In isn’t configured yet. Add your client IDs to ios/Config/Google.local.xcconfig."
            return
        }
        guard let presenter = Self.topViewController() else { return }
        isWorking = true
        defer { isWorking = false }
        do {
            let result = try await GIDSignIn.sharedInstance.signIn(withPresenting: presenter)
            try await adopt(result.user, registerWithBackend: true)
            GRHaptics.success()
        } catch {
            let nsError = error as NSError
            if nsError.domain == kGIDSignInErrorDomain, nsError.code == GIDSignInError.canceled.rawValue { return }
            lastError = APIError.userFacing(error, resource: "account")
        }
    }

    func useDemoSession() async {
        lastError = nil
        await APIClient.shared.setAccessToken(Self.demoToken)
        UserDefaults.standard.set(true, forKey: Self.demoKey)
        state = .demo
    }

    func signOut() async {
        if case .google = state {
            GIDSignIn.sharedInstance.signOut()
        }
        UserDefaults.standard.set(false, forKey: Self.demoKey)
        UserDefaults.standard.set(false, forKey: Self.localDevKey)
        await APIClient.shared.setAccessToken(nil)
        state = .signedOut
    }

    func handle(_ url: URL) -> Bool {
        GIDSignIn.sharedInstance.handle(url)
    }

    private func adopt(_ user: GIDGoogleUser, registerWithBackend: Bool) async throws {
        let refreshed = try await user.refreshTokensIfNeeded()
        guard let idToken = refreshed.idToken?.tokenString else {
            throw APIError.http(401, "Google didn’t return an ID token")
        }
        await APIClient.shared.setAccessToken(idToken)
        UserDefaults.standard.set(false, forKey: Self.demoKey)

        var name = refreshed.profile?.name
        var email = refreshed.profile?.email
        if registerWithBackend {
            do {
                let response = try await APIClient.shared.loginWithGoogle(idToken: idToken)
                name = response.user?.name ?? name
                email = response.user?.email ?? email
            } catch {
                lastError = "Signed in with Google, but the server didn’t accept the token. " + APIError.userFacing(error, resource: "account")
            }
        }
        state = .google(name: name, email: email)

        let storedName = UserDefaults.standard.string(forKey: GRSettingsKey.displayName) ?? ""
        if storedName.isEmpty, let name {
            UserDefaults.standard.set(name, forKey: GRSettingsKey.displayName)
        }
    }

    private static func topViewController() -> UIViewController? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let scene = scenes.first { $0.activationState == .foregroundActive } ?? scenes.first
        var top = scene?.keyWindow?.rootViewController
        while let presented = top?.presentedViewController {
            top = presented
        }
        return top
    }
}
