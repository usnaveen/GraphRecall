import Foundation
import Security

/// Metadata saved alongside the app-only refresh token so warm launches restore session identity
/// immediately and know when the shared access token needs proactive renewal.
struct StoredSessionMeta: Codable, Equatable, Sendable {
    let provider: String
    let name: String?
    let email: String?
    let expiresAt: Date
}

/// App-private Keychain store for `refresh_token` and session metadata.
/// Uses the app's private Keychain group (`<TeamID>.com.usnaveen.graphrecall`) rather than the
/// App Group shared group so `GraphRecallShare` can never access or rotate the refresh token.
enum AppAuthKeychain {
    private static let service = "com.usnaveen.graphrecall.app.auth"
    private static let refreshTokenAccount = "refresh_token"
    private static let sessionMetaAccount = "session_meta"
    private static let privateBundleId = "com.usnaveen.graphrecall"

    private static var privateAccessGroup: String? {
        GRShared.appIdentifierPrefix.map { "\($0)\(privateBundleId)" }
    }

    static func save(refreshToken: String, meta: StoredSessionMeta) {
        if let tokenData = refreshToken.data(using: .utf8) {
            writeData(tokenData, account: refreshTokenAccount)
        }
        if let metaData = try? JSONEncoder().encode(meta) {
            writeData(metaData, account: sessionMetaAccount)
        }
    }

    static func loadRefreshToken() -> String? {
        guard let data = readData(account: refreshTokenAccount),
              let token = String(data: data, encoding: .utf8),
              !token.isEmpty else {
            return nil
        }
        return token
    }

    static func loadMeta() -> StoredSessionMeta? {
        guard let data = readData(account: sessionMetaAccount) else { return nil }
        return try? JSONDecoder().decode(StoredSessionMeta.self, from: data)
    }

    static func clear() {
        deleteData(account: refreshTokenAccount)
        deleteData(account: sessionMetaAccount)
    }

    private static func baseQuery(account: String, withAccessGroup: Bool) -> [String: Any] {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        if withAccessGroup, let group = privateAccessGroup {
            query[kSecAttrAccessGroup as String] = group
        }
        return query
    }

    private static func readData(account: String) -> Data? {
        if privateAccessGroup != nil {
            let result = copyMatching(query: baseQuery(account: account, withAccessGroup: true))
            if result.status == errSecSuccess {
                return result.data
            }
            if result.status != errSecMissingEntitlement {
                return nil
            }
        }
        let fallback = copyMatching(query: baseQuery(account: account, withAccessGroup: false))
        return fallback.status == errSecSuccess ? fallback.data : nil
    }

    private static func copyMatching(query: [String: Any]) -> (status: OSStatus, data: Data?) {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else {
            return (status, nil)
        }
        return (status, data)
    }

    private static func writeData(_ data: Data, account: String) {
        if privateAccessGroup != nil {
            let status = upsertData(data, account: account, withAccessGroup: true)
            if status != errSecMissingEntitlement {
                return
            }
        }
        _ = upsertData(data, account: account, withAccessGroup: false)
    }

    private static func upsertData(_ data: Data, account: String, withAccessGroup: Bool) -> OSStatus {
        let query = baseQuery(account: account, withAccessGroup: withAccessGroup)
        SecItemDelete(query as CFDictionary)
        var addQuery = query
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(addQuery as CFDictionary, nil)
    }

    private static func deleteData(account: String) {
        if privateAccessGroup != nil {
            SecItemDelete(baseQuery(account: account, withAccessGroup: true) as CFDictionary)
        }
        SecItemDelete(baseQuery(account: account, withAccessGroup: false) as CFDictionary)
    }
}
