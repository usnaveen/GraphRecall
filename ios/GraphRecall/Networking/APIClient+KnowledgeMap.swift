import Foundation

/// Knowledge map, capability profile, resume and map-the-territory answers.
extension APIClient {
    private func kmPath(_ raw: String) -> String {
        raw.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? raw
    }

    // MARK: Knowledge map

    func knowledgeSummary() async throws -> KnowledgeSummary {
        try await get("/api/knowledge-map/summary")
    }

    func assessKnowledge(_ names: [String]) async throws -> [KnowledgeAssessment] {
        let r: KnowledgeAssessResponse = try await post("/api/knowledge-map/assess", body: AssessBody(names: names))
        return r.results
    }

    func exposureQuestions(limit: Int = 5) async throws -> [ExposureQuestion] {
        let r: ExposureQuestionsResponse = try await get(
            "/api/knowledge-map/questions", query: [URLQueryItem(name: "limit", value: String(limit))])
        return r.questions
    }

    func rateExposure(name: String, level: Int) async throws -> KnowledgeAssessment {
        try await post("/api/knowledge-map/self-rating", body: SelfRatingBody(name: name, level: level))
    }

    // MARK: Profile

    func capabilityProfile() async throws -> UserProfileInfo {
        try await get("/api/profile")
    }

    func saveCapabilityProfile(_ profile: UserProfileInfo) async throws -> UserProfileInfo {
        let data = try JSONEncoder().encode(profile)
        return try await send("/api/profile", method: "PUT", body: data)
    }

    func courses() async throws -> [UserCourse] {
        let r: UserCoursesResponse = try await get("/api/profile/courses")
        return r.courses
    }

    func addCourse(_ body: CourseBody) async throws -> UserCourse {
        try await post("/api/profile/courses", body: body)
    }

    func deleteCourse(id: String) async throws {
        try await sendNoContent("/api/profile/courses/\(kmPath(id))", method: "DELETE", body: nil)
    }

    func projects() async throws -> [UserProject] {
        let r: UserProjectsResponse = try await get("/api/profile/projects")
        return r.projects
    }

    func addProject(_ body: ProjectBody) async throws -> UserProject {
        try await post("/api/profile/projects", body: body)
    }

    func deleteProject(id: String) async throws {
        try await sendNoContent("/api/profile/projects/\(kmPath(id))", method: "DELETE", body: nil)
    }

    // MARK: Resume

    func resumeOverview() async throws -> ResumeOverview {
        try await get("/api/profile/resume")
    }

    /// Text is extracted on device (PDFKit); the backend strips contact details before storing it.
    func uploadResume(text: String, fileName: String?) async throws -> ResumeOverview {
        try await post("/api/profile/resume", body: ResumeUploadBody(text: text, fileName: fileName), timeout: 120)
    }

    // MARK: Territory

    func answerTerritory(conceptId: String, answer: String) async throws -> TerritoryResult {
        try await post("/api/territory/\(kmPath(conceptId))/answer", body: TerritoryAnswerBody(answer: answer))
    }
}
