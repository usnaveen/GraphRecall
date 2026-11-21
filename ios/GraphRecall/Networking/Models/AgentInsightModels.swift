import Foundation

struct AgentVerifiedQuote: Codable, Sendable, Hashable, Identifiable {
    let chunkId: String
    let noteId: String
    let noteTitle: String
    let quote: String

    var id: String { "\(chunkId)-\(quote.prefix(24))" }

    enum CodingKeys: String, CodingKey {
        case chunkId = "chunk_id"
        case noteId = "note_id"
        case noteTitle = "note_title"
        case quote
    }
}

struct AgentFeedCard: Codable, Sendable, Hashable, Identifiable {
    let id: String
    let cardType: String
    let insightType: String
    let title: String
    let bodyMd: String
    let conceptIds: [String]
    let sourceQuotes: [AgentVerifiedQuote]
    let createdAt: Date
    let isDemo: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case cardType = "card_type"
        case insightType = "insight_type"
        case title
        case bodyMd = "body_md"
        case conceptIds = "concept_ids"
        case sourceQuotes = "source_quotes"
        case createdAt = "created_at"
    }

    init(
        id: String,
        cardType: String = "agent_insight",
        insightType: String,
        title: String,
        bodyMd: String,
        conceptIds: [String] = [],
        sourceQuotes: [AgentVerifiedQuote] = [],
        createdAt: Date = Date(),
        isDemo: Bool = false
    ) {
        self.id = id
        self.cardType = cardType
        self.insightType = insightType
        self.title = title
        self.bodyMd = bodyMd
        self.conceptIds = conceptIds
        self.sourceQuotes = sourceQuotes
        self.createdAt = createdAt
        self.isDemo = isDemo
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        cardType = try c.decodeIfPresent(String.self, forKey: .cardType) ?? "agent_insight"
        insightType = try c.decode(String.self, forKey: .insightType)
        title = try c.decode(String.self, forKey: .title)
        bodyMd = try c.decode(String.self, forKey: .bodyMd)
        conceptIds = try c.decodeIfPresent([String].self, forKey: .conceptIds) ?? []
        sourceQuotes = try c.decodeIfPresent([AgentVerifiedQuote].self, forKey: .sourceQuotes) ?? []
        createdAt = try c.decodeIfPresent(Date.self, forKey: .createdAt) ?? Date()
        isDemo = false
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(cardType, forKey: .cardType)
        try c.encode(insightType, forKey: .insightType)
        try c.encode(title, forKey: .title)
        try c.encode(bodyMd, forKey: .bodyMd)
        try c.encode(conceptIds, forKey: .conceptIds)
        try c.encode(sourceQuotes, forKey: .sourceQuotes)
        try c.encode(createdAt, forKey: .createdAt)
    }

    var typeLabel: String {
        switch insightType.lowercased() {
        case "connection": return "Connection"
        case "conflict": return "Conflict"
        case "remedial": return "Remedial"
        case "briefing": return "Briefing"
        default: return "Insight"
        }
    }

    var typeIcon: String {
        switch insightType.lowercased() {
        case "connection": return "link"
        case "conflict": return "exclamationmark.triangle.fill"
        case "remedial": return "arrow.counterclockwise"
        case "briefing": return "sun.max.fill"
        default: return "sparkles"
        }
    }

    static let demoSamples: [AgentFeedCard] = [
        AgentFeedCard(
            id: "demo-insight-connection-1",
            insightType: "connection",
            title: "Residual skip paths complement LayerNorm stability",
            bodyMd: "Your newer notes on residual connections address gradient attenuation directly alongside normalization.",
            conceptIds: ["Residual Connections", "Vanishing Gradients"],
            sourceQuotes: [
                AgentVerifiedQuote(
                    chunkId: "demo-c1",
                    noteId: "demo-n1",
                    noteTitle: "Deep Residual Learning",
                    quote: "skip connections preserve gradient magnitude across deep layers"
                ),
                AgentVerifiedQuote(
                    chunkId: "demo-c2",
                    noteId: "demo-n2",
                    noteTitle: "Optimization Notes",
                    quote: "repeated sigmoid derivatives shrink gradients exponentially"
                )
            ],
            isDemo: true
        ),
        AgentFeedCard(
            id: "demo-insight-remedial-1",
            insightType: "remedial",
            title: "Revisit the 2/L step-size bound before next quiz",
            bodyMd: "You missed this card twice recently. Verify the smoothness stability condition before increasing learning rate.",
            conceptIds: ["Gradient Descent", "L-Smoothness"],
            sourceQuotes: [
                AgentVerifiedQuote(
                    chunkId: "demo-c3",
                    noteId: "demo-n3",
                    noteTitle: "Convex Optimization",
                    quote: "Step size eta must remain below 2/L for L-smooth convex functions"
                )
            ],
            isDemo: true
        )
    ]
}

struct AgentFeedCardListResponse: Codable, Sendable {
    let cards: [AgentFeedCard]
    let total: Int
}

struct AgentInsightActionResponse: Codable, Sendable {
    let id: String
    let status: String
}
