import Foundation

/// Body for `POST /auth/google` (`backend/routers/auth.py` → `GoogleAuthRequest.token`).
struct GoogleAuthRequest: Codable {
    let idToken: String
    enum CodingKeys: String, CodingKey { case idToken = "token" }
}

struct AuthUser: Codable, Identifiable {
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

/// `/auth/google` returns `{status, user, token}` — the token echoes the Google ID token,
/// which stays the bearer for later calls.
struct AuthResponse: Codable {
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
