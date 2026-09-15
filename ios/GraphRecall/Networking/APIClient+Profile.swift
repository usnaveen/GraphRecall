import Foundation

struct ProfileUpdateBody: Encodable {
    let settings: [String: Int]
    let dailyLimit: Int?

    enum CodingKeys: String, CodingKey {
        case settings
        case dailyLimit = "daily_limit"
    }
}

struct ProfileUpdateResponse: Decodable {
    let status: String?
}

extension APIClient {
    /// PATCH `/auth/profile` — merges study preferences into `users.settings_json`.
    func updateStudyPreferences(dailyGoal: Int, newCardsPerDay: Int) async throws {
        var settings = ["new_cards_per_day": newCardsPerDay]
        if dailyGoal > 0 { settings["daily_goal"] = dailyGoal }
        let body = try JSONEncoder().encode(ProfileUpdateBody(settings: settings, dailyLimit: newCardsPerDay))
        let _: ProfileUpdateResponse = try await send("/auth/profile", method: "PATCH", body: body)
    }
}
