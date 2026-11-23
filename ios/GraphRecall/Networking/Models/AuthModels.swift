import Foundation

/// Body for `POST /auth/google` (`backend/routers/auth.py` → `GoogleAuthRequest.token`).
struct GoogleAuthRequest: Codable, Sendable {
    let idToken: String
    enum CodingKeys: String, CodingKey { case idToken = "token" }
}

/// Body for `POST /auth/session/google` (`GoogleSessionRequest.id_token`).
struct GoogleSessionRequest: Encodable, Sendable {
    let idToken: String
    enum CodingKeys: String, CodingKey { case idToken = "id_token" }
}

/// Response for `POST /auth/apple/nonce`.
struct AppleNonceResponse: Decodable, Sendable {
    let nonce: String
    let expiresIn: Int

    enum CodingKeys: String, CodingKey {
        case nonce
        case expiresIn = "expires_in"
    }
}

/// Optional first-time full name passed to `POST /auth/apple`.
struct AppleFullNamePayload: Encodable, Sendable {
    let given: String?
    let family: String?
}

/// Body for `POST /auth/apple`.
struct AppleAuthRequest: Encodable, Sendable {
    let identityToken: String
    let nonce: String
    let authorizationCode: String?
    let fullName: AppleFullNamePayload?

    enum CodingKeys: String, CodingKey {
        case identityToken = "identity_token"
        case nonce
        case authorizationCode = "authorization_code"
        case fullName = "full_name"
    }
}

/// Body for `POST /auth/refresh` and `POST /auth/logout`.
struct RefreshTokenRequest: Encodable, Sendable {
    let refreshToken: String
    enum CodingKeys: String, CodingKey { case refreshToken = "refresh_token" }
}

struct AuthUser: Codable, Identifiable, Sendable, Equatable {
    let id: String
    let email: String?
    let name: String?
    let picture: String?

    enum CodingKeys: String, CodingKey {
        case id, email, name, picture
        case profilePicture = "profile_picture"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let s = try? c.decode(String.self, forKey: .id) {
            id = s
        } else {
            id = String(try c.decode(Int.self, forKey: .id))
        }
        email = try c.decodeIfPresent(String.self, forKey: .email)
        name = try c.decodeIfPresent(String.self, forKey: .name)
        picture = try c.decodeIfPresent(String.self, forKey: .profilePicture)
            ?? c.decodeIfPresent(String.self, forKey: .picture)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encodeIfPresent(email, forKey: .email)
        try c.encodeIfPresent(name, forKey: .name)
        try c.encodeIfPresent(picture, forKey: .profilePicture)
    }
}

/// Session response returned by `/auth/apple`, `/auth/session/google`, and `/auth/refresh`.
struct AuthSessionResponse: Decodable, Sendable {
    let accessToken: String
    let refreshToken: String
    let tokenType: String
    let expiresIn: Int
    let user: AuthUser

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case tokenType = "token_type"
        case expiresIn = "expires_in"
        case user
    }
}

/// Legacy `/auth/google` response shape `{status, user, token}`.
struct AuthResponse: Codable, Sendable {
    let accessToken: String?
    let user: AuthUser?

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case token
        case user
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        accessToken = try c.decodeIfPresent(String.self, forKey: .token)
            ?? c.decodeIfPresent(String.self, forKey: .accessToken)
        user = try c.decodeIfPresent(AuthUser.self, forKey: .user)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(accessToken, forKey: .token)
        try c.encodeIfPresent(user, forKey: .user)
    }
}
