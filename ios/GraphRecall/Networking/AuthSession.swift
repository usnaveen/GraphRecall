import AuthenticationServices
import CryptoKit
@preconcurrency import GoogleSignIn
import SwiftUI
import UIKit

/// Owns authentication state and GraphRecall session lifecycle (Sign in with Apple, Google Sign-In,
/// single-flight refresh token rotation, and local dev/demo modes).
@MainActor
@Observable
final class AuthSession {
    static let shared = AuthSession()

    enum State: Equatable {
        case signedOut
        case demo
        /// Docker backend with DEBUG=true, which accepts `test-token` as a test user.
        case localDev
        case apple(name: String?, email: String?)
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
    private static let proactiveRefreshWindowSeconds: TimeInterval = 300

    private var currentAccessToken: String?
    private var accessTokenExpiresAt: Date?
    private var inFlightRefreshTask: Task<String?, Never>?
    private var didRegisterTokenProvider = false
    private var appleCoordinator: AppleSignInCoordinator?

    /// True once `GIDClientID` in Info.plist holds a real client ID (see ios/Config/Google.local.xcconfig.example).
    var isGoogleConfigured: Bool {
        let clientId = Bundle.main.object(forInfoDictionaryKey: "GIDClientID") as? String ?? ""
        return clientId.hasSuffix(".apps.googleusercontent.com")
    }

    var isSignedIn: Bool { state != .signedOut }

    /// The name the account came with (Apple or Google), when there is one.
    var accountName: String? {
        switch state {
        case .apple(let name, _), .google(let name, _):
            let trimmed = name?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return trimmed.isEmpty ? nil : trimmed
        default:
            return nil
        }
    }

    var statusLabel: String {
        switch state {
        case .signedOut: return "Not signed in"
        case .demo: return "Demo session"
        case .localDev: return "Local Docker backend · test user"
        case .apple(let name, let email):
            if let email, !email.isEmpty { return "Signed in with Apple · \(email)" }
            if let name, !name.isEmpty { return "Signed in with Apple · \(name)" }
            return "Signed in with Apple"
        case .google(let name, let email):
            if let email, !email.isEmpty { return "Signed in as \(email)" }
            if let name, !name.isEmpty { return "Signed in as \(name)" }
            return "Signed in with Google"
        }
    }

    /// Lowercase hex SHA-256 matching backend `sessions.sha256_hex` for Sign in with Apple nonces.
    static func sha256Hex(_ input: String) -> String {
        let digest = SHA256.hash(data: Data(input.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    /// Registers `APIClient`'s token provider and restores an existing Apple, Google, dev, or demo session.
    func restore() async {
        await ensureTokenProviderRegistered()
        if ProcessInfo.processInfo.environment["GR_UITEST"] != nil { return }

        if let refreshToken = AppAuthKeychain.loadRefreshToken() {
            let meta = AppAuthKeychain.loadMeta()
            let cachedAccess = GRSharedAuth.bearerToken
            let provider = meta?.provider ?? "apple"
            state = provider == "apple"
                ? .apple(name: meta?.name, email: meta?.email)
                : .google(name: meta?.name, email: meta?.email)

            if let cachedAccess, !cachedAccess.isEmpty,
               let expiresAt = meta?.expiresAt,
               expiresAt.timeIntervalSinceNow > Self.proactiveRefreshWindowSeconds {
                currentAccessToken = cachedAccess
                accessTokenExpiresAt = expiresAt
                await APIClient.shared.setAccessToken(cachedAccess)
                return
            }

            let refreshed = await performSingleFlightRefresh(refreshToken: refreshToken)
            if refreshed != nil { return }
            if state != .signedOut, let cachedAccess, !cachedAccess.isEmpty {
                currentAccessToken = cachedAccess
                accessTokenExpiresAt = meta?.expiresAt
                await APIClient.shared.setAccessToken(cachedAccess)
            }
            return
        }

        // Seamless one-time migration for existing Google Sign-In installs onto GraphRecall sessions.
        if isGoogleConfigured, GIDSignIn.sharedInstance.hasPreviousSignIn() {
            do {
                let user = try await GIDSignIn.sharedInstance.restorePreviousSignIn()
                try await exchangeAndAdoptGoogle(user)
                return
            } catch {
                lastError = "Your Google session expired — sign in again."
            }
        }

        if UserDefaults.standard.bool(forKey: Self.localDevKey) {
            currentAccessToken = Self.localDevToken
            accessTokenExpiresAt = nil
            await APIClient.shared.setAccessToken(Self.localDevToken)
            state = .localDev
            return
        }
        if UserDefaults.standard.bool(forKey: Self.demoKey) {
            currentAccessToken = Self.demoToken
            accessTokenExpiresAt = nil
            await APIClient.shared.setAccessToken(Self.demoToken)
            state = .demo
        }
    }

    /// Refreshes proactively when the current session access token has less than 5 minutes left.
    func refreshIfNeeded() async {
        await ensureTokenProviderRegistered()
        switch state {
        case .apple, .google:
            _ = await tokenForRequest(forceRefresh: false, failedToken: nil)
        case .signedOut, .demo, .localDev:
            return
        }
    }

    func signInWithApple() async {
        await ensureTokenProviderRegistered()
        lastError = nil
        isWorking = true
        defer {
            isWorking = false
            appleCoordinator = nil
        }

        do {
            let nonceResponse = try await APIClient.shared.fetchAppleNonce()
            let coordinator = AppleSignInCoordinator()
            appleCoordinator = coordinator
            let credential = try await coordinator.perform(hashedNonce: Self.sha256Hex(nonceResponse.nonce))
            let request = AppleAuthRequest(
                identityToken: credential.identityToken,
                nonce: nonceResponse.nonce,
                authorizationCode: credential.authorizationCode,
                fullName: credential.fullName
            )
            let sessionResponse = try await APIClient.shared.loginWithApple(request)
            await adoptSession(sessionResponse, provider: "apple")
            GRHaptics.success()
        } catch let appleError as ASAuthorizationError where appleError.code == .canceled {
            return
        } catch {
            lastError = APIError.userFacing(error, resource: "account")
        }
    }

    func signInWithGoogle() async {
        await ensureTokenProviderRegistered()
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
            try await exchangeAndAdoptGoogle(result.user)
            GRHaptics.success()
        } catch {
            let nsError = error as NSError
            if nsError.domain == kGIDSignInErrorDomain, nsError.code == GIDSignInError.canceled.rawValue { return }
            lastError = APIError.userFacing(error, resource: "account")
        }
    }

    /// Points the app at `docker compose up` on this Mac and signs in as the backend's test user.
    func useLocalDevSession() async {
        await ensureTokenProviderRegistered()
        lastError = nil
        AppAuthKeychain.clear()
        currentAccessToken = Self.localDevToken
        accessTokenExpiresAt = nil
        UserDefaults.standard.set(Self.localDevBaseURL, forKey: APIConfig.apiBaseDefaultsKey)
        UserDefaults.standard.set(true, forKey: Self.localDevKey)
        UserDefaults.standard.set(false, forKey: Self.demoKey)
        await APIClient.shared.setAccessToken(Self.localDevToken)
        state = .localDev
    }

    func useDemoSession() async {
        await ensureTokenProviderRegistered()
        lastError = nil
        AppAuthKeychain.clear()
        currentAccessToken = Self.demoToken
        accessTokenExpiresAt = nil
        await APIClient.shared.setAccessToken(Self.demoToken)
        UserDefaults.standard.set(true, forKey: Self.demoKey)
        UserDefaults.standard.set(false, forKey: Self.localDevKey)
        state = .demo
    }

    func signOut(revokeOnServer: Bool = true) async {
        if revokeOnServer, let refreshToken = AppAuthKeychain.loadRefreshToken() {
            try? await APIClient.shared.logoutSession(refreshToken: refreshToken)
        }
        if case .google = state {
            GIDSignIn.sharedInstance.signOut()
        }
        await clearSessionLocally()
    }

    func handle(_ url: URL) -> Bool {
        GIDSignIn.sharedInstance.handle(url)
    }

    #if DEBUG
    func resetForTesting() async {
        await clearSessionLocally()
    }

    func seedSessionForTesting(accessToken: String, refreshToken: String, expiresIn: Int,
                               name: String = "Test User") async {
        await ensureTokenProviderRegistered()
        // Switching accounts: grades queued by the previous one must not be sent as this one.
        if AppAuthKeychain.loadMeta()?.name != name { await OfflineReviewStore.shared.clear() }
        let expiresAt = Date().addingTimeInterval(TimeInterval(expiresIn))
        currentAccessToken = accessToken
        accessTokenExpiresAt = expiresAt
        AppAuthKeychain.save(
            refreshToken: refreshToken,
            meta: StoredSessionMeta(provider: "apple", name: name, email: nil, expiresAt: expiresAt)
        )
        await APIClient.shared.setAccessToken(accessToken)
        state = .apple(name: name, email: nil)
    }
    #endif

    // MARK: - Private session helpers

    private func ensureTokenProviderRegistered() async {
        guard !didRegisterTokenProvider else { return }
        didRegisterTokenProvider = true
        await APIClient.shared.setTokenProvider { forceRefresh, failedToken in
            await AuthSession.shared.tokenForRequest(forceRefresh: forceRefresh, failedToken: failedToken)
        }
    }

    private func exchangeAndAdoptGoogle(_ user: GIDGoogleUser) async throws {
        let refreshed = try await user.refreshTokensIfNeeded()
        guard let idToken = refreshed.idToken?.tokenString else {
            throw APIError.http(401, "Google didn’t return an ID token")
        }
        let sessionResponse = try await APIClient.shared.exchangeGoogleSession(idToken: idToken)
        await adoptSession(sessionResponse, provider: "google")
    }

    private func adoptSession(_ response: AuthSessionResponse, provider: String) async {
        let ttl = max(response.expiresIn, 60)
        let expiresAt = Date().addingTimeInterval(TimeInterval(ttl))
        currentAccessToken = response.accessToken
        accessTokenExpiresAt = expiresAt
        AppAuthKeychain.save(
            refreshToken: response.refreshToken,
            meta: StoredSessionMeta(
                provider: provider,
                name: response.user.name,
                email: response.user.email,
                expiresAt: expiresAt
            )
        )
        await APIClient.shared.setAccessToken(response.accessToken)
        UserDefaults.standard.set(false, forKey: Self.demoKey)
        UserDefaults.standard.set(false, forKey: Self.localDevKey)
        lastError = nil
        state = provider == "apple"
            ? .apple(name: response.user.name, email: response.user.email)
            : .google(name: response.user.name, email: response.user.email)

        let storedName = UserDefaults.standard.string(forKey: GRSettingsKey.displayName) ?? ""
        if storedName.isEmpty, let name = response.user.name, !name.isEmpty {
            UserDefaults.standard.set(name, forKey: GRSettingsKey.displayName)
        }
    }

    private func clearSessionLocally() async {
        inFlightRefreshTask?.cancel()
        inFlightRefreshTask = nil
        currentAccessToken = nil
        accessTokenExpiresAt = nil
        UserDefaults.standard.set(false, forKey: Self.demoKey)
        UserDefaults.standard.set(false, forKey: Self.localDevKey)
        AppAuthKeychain.clear()
        GRSharedAuth.clear()
        ResumeFileStore.removeAll() // the original resume PDF is personal and stays with the account
        await OfflineReviewStore.shared.clear() // queued grades belong to the account that made them
        await APIClient.shared.setAccessToken(nil)
        state = .signedOut
    }

    /// Single-flight bearer resolution: refreshes when `< 5 min` remain or after a 401.
    private func tokenForRequest(forceRefresh: Bool, failedToken: String?) async -> String? {
        if let inFlightRefreshTask {
            return await inFlightRefreshTask.value
        }

        if forceRefresh {
            // If an earlier concurrent caller already rotated past `failedToken`, reuse its fresh token.
            if let failedToken,
               let currentAccessToken,
               !currentAccessToken.isEmpty,
               currentAccessToken != failedToken,
               let expiresAt = accessTokenExpiresAt,
               expiresAt.timeIntervalSinceNow > 60 {
                return currentAccessToken
            }
            guard let refreshToken = AppAuthKeychain.loadRefreshToken() else {
                return nil
            }
            return await performSingleFlightRefresh(refreshToken: refreshToken)
        }

        if let currentAccessToken, !currentAccessToken.isEmpty {
            guard let expiresAt = accessTokenExpiresAt else {
                return currentAccessToken
            }
            if expiresAt.timeIntervalSinceNow > Self.proactiveRefreshWindowSeconds {
                return currentAccessToken
            }
            if let refreshToken = AppAuthKeychain.loadRefreshToken() {
                if let refreshed = await performSingleFlightRefresh(refreshToken: refreshToken) {
                    return refreshed
                }
            }
            return expiresAt.timeIntervalSinceNow > 10 ? currentAccessToken : nil
        }

        if let refreshToken = AppAuthKeychain.loadRefreshToken() {
            return await performSingleFlightRefresh(refreshToken: refreshToken)
        }
        return nil
    }

    private func performSingleFlightRefresh(refreshToken: String) async -> String? {
        if let existing = inFlightRefreshTask {
            return await existing.value
        }

        let existingMeta = AppAuthKeychain.loadMeta()
        let fallbackProvider: String = {
            if let provider = existingMeta?.provider { return provider }
            if case .apple = state { return "apple" }
            return "google"
        }()

        let task = Task<String?, Never> { @MainActor in
            defer { inFlightRefreshTask = nil }
            do {
                let response = try await APIClient.shared.refreshSession(refreshToken: refreshToken)
                await adoptSession(response, provider: fallbackProvider)
                return response.accessToken
            } catch let APIError.http(code, _) where code == 401 || code == 403 {
                await clearSessionLocally()
                lastError = "Your session expired — please sign in again."
                return nil
            } catch {
                // Keep refresh_token intact on transient offline / 5xx errors so the next attempt can retry.
                return nil
            }
        }
        inFlightRefreshTask = task
        return await task.value
    }

    static func resolvePresentationAnchor() -> ASPresentationAnchor {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let activeScene = scenes.first { $0.activationState == .foregroundActive } ?? scenes.first
        if let existing = activeScene?.keyWindow ?? activeScene?.windows.first {
            return existing
        }
        if let activeScene {
            return ASPresentationAnchor(windowScene: activeScene)
        }
        return ASPresentationAnchor()
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

private struct AppleCredentialPayload: Sendable {
    let identityToken: String
    let authorizationCode: String?
    let fullName: AppleFullNamePayload?
}

private final class AppleSignInCoordinator: NSObject,
    ASAuthorizationControllerDelegate,
    ASAuthorizationControllerPresentationContextProviding,
    @unchecked Sendable
{
    private var continuation: CheckedContinuation<AppleCredentialPayload, Error>?
    private let lock = NSLock()

    @MainActor
    func perform(hashedNonce: String) async throws -> AppleCredentialPayload {
        try await withCheckedThrowingContinuation { continuation in
            lock.lock()
            self.continuation = continuation
            lock.unlock()

            let request = ASAuthorizationAppleIDProvider().createRequest()
            request.requestedScopes = [.fullName, .email]
            request.nonce = hashedNonce

            let controller = ASAuthorizationController(authorizationRequests: [request])
            controller.delegate = self
            controller.presentationContextProvider = self
            controller.performRequests()
        }
    }

    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        MainActor.assumeIsolated {
            AuthSession.resolvePresentationAnchor()
        }
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
              let tokenData = credential.identityToken,
              let identityToken = String(data: tokenData, encoding: .utf8),
              !identityToken.isEmpty else {
            finish(throwing: APIError.http(401, "Apple didn’t return an identity token."))
            return
        }

        let authCode = credential.authorizationCode
            .flatMap { String(data: $0, encoding: .utf8) }
            .flatMap { $0.isEmpty ? nil : $0 }

        let given = credential.fullName?.givenName?.trimmingCharacters(in: .whitespacesAndNewlines)
        let family = credential.fullName?.familyName?.trimmingCharacters(in: .whitespacesAndNewlines)
        let hasName = (given?.isEmpty == false) || (family?.isEmpty == false)
        let fullName = hasName ? AppleFullNamePayload(given: given, family: family) : nil

        finish(returning: AppleCredentialPayload(
            identityToken: identityToken,
            authorizationCode: authCode,
            fullName: fullName
        ))
    }

    func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        finish(throwing: error)
    }

    private func finish(returning payload: AppleCredentialPayload) {
        takeContinuation()?.resume(returning: payload)
    }

    private func finish(throwing error: Error) {
        takeContinuation()?.resume(throwing: error)
    }

    private func takeContinuation() -> CheckedContinuation<AppleCredentialPayload, Error>? {
        lock.lock()
        defer { lock.unlock() }
        let cont = continuation
        continuation = nil
        return cont
    }
}
