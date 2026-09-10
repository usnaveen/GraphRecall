import Foundation

struct GoogleAuthRequest: Codable {
    let idToken: String
    enum CodingKeys: String, CodingKey { case idToken = "id_token" }
}

struct AuthUser: Codable, Identifiable {
    let id: String
    let email: String?
    let name: String?
    let picture: String?
}

struct AuthResponse: Codable {
    let accessToken: String
    let user: AuthUser?
    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case user
    }
}
