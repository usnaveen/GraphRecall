import Foundation

// MARK: - Agent bridge wire models
//
// Mirrors `backend/agent_bridge/router.py` (PR #3, `feat/agent-bridge-mcp`).
// Every route lives under `/api/agent-bridge` and only exists when the server runs with
// `AGENT_BRIDGE_ENABLED=1`; otherwise they 404 (see `AgentBridgeCapability`).
//
// Timestamps: since PR #3 @ cadf9c8 the bridge returns ISO 8601 with `T` and an offset
// (`2026-11-24T06:11:10.751395+00:00`, `target_date` as `2026-11-24`). They are kept as raw
// strings and parsed by `AgentBridgeDate.parse`, which handles ISO first (with or without
// fractional seconds, any digit count, `Z` or offset) and still accepts the old Python
// `str(datetime)` form as a fallback for older servers / cached rows.

enum AgentBridgeDate {
    // Formatters are configured once and only read afterwards.
    nonisolated(unsafe) private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    nonisolated(unsafe) private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private static let dayOnly: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    /// Accepts ISO-8601 (with or without fractional seconds), Python `str(datetime)` and `yyyy-MM-dd`.
    static func parse(_ raw: String?) -> Date? {
        guard var s = raw?.trimmingCharacters(in: .whitespaces), !s.isEmpty else { return nil }
        if s.count == 10, let d = dayOnly.date(from: s) { return d }
        if s.count > 10, s[s.index(s.startIndex, offsetBy: 10)] == " " {
            s.replaceSubrange(s.index(s.startIndex, offsetBy: 10)...s.index(s.startIndex, offsetBy: 10), with: "T")
        }
        // Python can emit 6 fractional digits; ISO8601DateFormatter wants at most 3.
        if let dot = s.firstIndex(of: "."), let end = s[dot...].firstIndex(where: { $0 == "+" || $0 == "-" || $0 == "Z" }) {
            let digits = s[s.index(after: dot)..<end]
            if digits.count > 3 {
                s.replaceSubrange(s.index(after: dot)..<end, with: String(digits.prefix(3)))
            }
        }
        return isoFractional.date(from: s) ?? iso.date(from: s)
    }
}

/// The single gate for agent-provided links (card `source_url`, citation URLs, markdown links in
/// answers). Only absolute http(s) URLs with a host and no embedded credentials pass; everything
/// else (`javascript:`, `data:`, `file:`, `tel:`, custom app schemes, `https://good.com@evil.com`,
/// strings with control characters) is rendered as plain text and never opened.
/// Covered by `GraphRecallTests/AgentBridgeURLTests.swift`.
enum AgentBridgeURL {
    static let maxLength = 2048

    static func safe(_ raw: String?) -> URL? {
        guard let raw = raw?.trimmingCharacters(in: .whitespacesAndNewlines),
              !raw.isEmpty, raw.count <= maxLength,
              raw.unicodeScalars.allSatisfy({ !CharacterSet.controlCharacters.contains($0) && $0 != " " }),
              let components = URLComponents(string: raw),
              let scheme = components.scheme?.lowercased(), scheme == "https" || scheme == "http",
              let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil,
              let url = components.url
        else { return nil }
        return url
    }

    /// Display host ("substack.com") so the user sees where a link really goes.
    static func displayHost(_ url: URL?) -> String? {
        guard let host = url?.host?.lowercased() else { return nil }
        return host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }
}

// MARK: Agent-curated feed items (approval inbox)

enum AgentFeedItemStatus: String, Codable, Sendable, CaseIterable {
    case pending, approved, rejected, expired
    case unknown

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = AgentFeedItemStatus(rawValue: raw) ?? .unknown
    }
}

enum AgentSourceKind: String, Codable, Sendable {
    case email, substack, web, exam, calendar, other

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = AgentSourceKind(rawValue: raw) ?? .other
    }

    var label: String {
        switch self {
        case .email: return "Email"
        case .substack: return "Substack"
        case .web: return "Web"
        case .exam: return "Exam"
        case .calendar: return "Calendar"
        case .other: return "Other"
        }
    }

    var systemImage: String {
        switch self {
        case .email: return "envelope.fill"
        case .substack: return "newspaper.fill"
        case .web: return "globe"
        case .exam: return "graduationcap.fill"
        case .calendar: return "calendar"
        case .other: return "sparkles"
        }
    }
}

struct AgentFlashcardBody: Codable, Sendable, Hashable {
    let front: String
    let back: String
}

struct AgentFeedItemBody: Codable, Sendable, Hashable {
    let flashcard: AgentFlashcardBody?
}

/// Row from `agent_feed_items` as returned by `GET /api/agent-bridge/feed-items`.
struct AgentFeedItem: Codable, Sendable, Identifiable, Hashable {
    let id: String
    let status: AgentFeedItemStatus
    let itemKind: String
    let title: String
    let summary: String
    let reason: String
    let sourceUrl: String?
    let sourceKind: AgentSourceKind
    let conceptIds: [String]
    let targetDate: String?
    let createdAt: String?
    let reviewedAt: String?
    let keyId: String?
    let bodyJson: AgentFeedItemBody?

    enum CodingKeys: String, CodingKey {
        case id, status, title, summary, reason
        case itemKind = "item_kind"
        case sourceUrl = "source_url"
        case sourceKind = "source_kind"
        case conceptIds = "concept_ids"
        case targetDate = "target_date"
        case createdAt = "created_at"
        case reviewedAt = "reviewed_at"
        case keyId = "key_id"
        case bodyJson = "body_json"
    }

    init(
        id: String, status: AgentFeedItemStatus = .pending, itemKind: String = "article",
        title: String, summary: String, reason: String, sourceUrl: String? = nil,
        sourceKind: AgentSourceKind = .web, conceptIds: [String] = [], targetDate: String? = nil,
        createdAt: String? = nil, reviewedAt: String? = nil, keyId: String? = nil,
        bodyJson: AgentFeedItemBody? = nil
    ) {
        self.id = id; self.status = status; self.itemKind = itemKind; self.title = title
        self.summary = summary; self.reason = reason; self.sourceUrl = sourceUrl
        self.sourceKind = sourceKind; self.conceptIds = conceptIds; self.targetDate = targetDate
        self.createdAt = createdAt; self.reviewedAt = reviewedAt; self.keyId = keyId
        self.bodyJson = bodyJson
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        status = try c.decodeIfPresent(AgentFeedItemStatus.self, forKey: .status) ?? .pending
        itemKind = try c.decodeIfPresent(String.self, forKey: .itemKind) ?? "article"
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        summary = try c.decodeIfPresent(String.self, forKey: .summary) ?? ""
        reason = try c.decodeIfPresent(String.self, forKey: .reason) ?? ""
        sourceUrl = try c.decodeIfPresent(String.self, forKey: .sourceUrl)
        sourceKind = try c.decodeIfPresent(AgentSourceKind.self, forKey: .sourceKind) ?? .other
        conceptIds = try c.decodeIfPresent([String].self, forKey: .conceptIds) ?? []
        targetDate = try c.decodeIfPresent(String.self, forKey: .targetDate)
        createdAt = try c.decodeIfPresent(String.self, forKey: .createdAt)
        reviewedAt = try c.decodeIfPresent(String.self, forKey: .reviewedAt)
        keyId = try c.decodeIfPresent(String.self, forKey: .keyId)
        // `body_json` is `{}` for plain articles; tolerate anything unexpected.
        bodyJson = try? c.decodeIfPresent(AgentFeedItemBody.self, forKey: .bodyJson)
    }

    var safeSourceURL: URL? { AgentBridgeURL.safe(sourceUrl) }
    var sourceHost: String? { AgentBridgeURL.displayHost(safeSourceURL) }
    var target: Date? { AgentBridgeDate.parse(targetDate) }
    var flashcard: AgentFlashcardBody? { bodyJson?.flashcard }
}

struct AgentFeedItemsResponse: Decodable, Sendable {
    let items: [AgentFeedItem]
}

struct AgentFeedItemEnvelope: Decodable, Sendable {
    let item: AgentFeedItem
}

// MARK: "Ask my agent" requests

enum AgentRequestStatus: String, Codable, Sendable {
    case queued, claimed, answered, failed, cancelled, expired
    case unknown

    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = AgentRequestStatus(rawValue: raw) ?? .unknown
    }

    var isTerminal: Bool {
        switch self {
        case .answered, .failed, .cancelled, .expired: return true
        case .queued, .claimed, .unknown: return false
        }
    }

    var label: String {
        switch self {
        case .queued: return "Waiting for your agent…"
        case .claimed: return "Your agent is researching…"
        case .answered: return "Answered by your agent"
        case .failed: return "Your agent couldn\u{2019}t answer"
        case .cancelled: return "Cancelled"
        case .expired: return "Expired before your agent picked it up"
        case .unknown: return "Unknown status"
        }
    }
}

struct AgentCitation: Codable, Sendable, Hashable {
    let title: String
    let url: String?

    var safeURL: URL? { AgentBridgeURL.safe(url) }
}

struct AgentAnswerExtras: Codable, Sendable, Hashable {
    let citations: [AgentCitation]?
}

/// `_request_view` in the bridge router.
struct AgentRequest: Codable, Sendable, Identifiable, Hashable {
    let id: String
    let status: AgentRequestStatus
    let question: String
    let conversationId: String?
    let createdAt: String?
    let claimedAt: String?
    let answeredAt: String?
    let answerText: String?
    let answerJson: AgentAnswerExtras?
    let error: String?
    let expiresAt: String?

    enum CodingKeys: String, CodingKey {
        case id, status, question, error
        case conversationId = "conversation_id"
        case createdAt = "created_at"
        case claimedAt = "claimed_at"
        case answeredAt = "answered_at"
        case answerText = "answer_text"
        case answerJson = "answer_json"
        case expiresAt = "expires_at"
    }

    init(
        id: String, status: AgentRequestStatus, question: String, conversationId: String? = nil,
        createdAt: String? = nil, claimedAt: String? = nil, answeredAt: String? = nil,
        answerText: String? = nil, answerJson: AgentAnswerExtras? = nil, error: String? = nil,
        expiresAt: String? = nil
    ) {
        self.id = id; self.status = status; self.question = question
        self.conversationId = conversationId; self.createdAt = createdAt; self.claimedAt = claimedAt
        self.answeredAt = answeredAt; self.answerText = answerText; self.answerJson = answerJson
        self.error = error; self.expiresAt = expiresAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        status = try c.decodeIfPresent(AgentRequestStatus.self, forKey: .status) ?? .unknown
        question = try c.decodeIfPresent(String.self, forKey: .question) ?? ""
        conversationId = try c.decodeIfPresent(String.self, forKey: .conversationId)
        createdAt = try c.decodeIfPresent(String.self, forKey: .createdAt)
        claimedAt = try c.decodeIfPresent(String.self, forKey: .claimedAt)
        answeredAt = try c.decodeIfPresent(String.self, forKey: .answeredAt)
        answerText = try c.decodeIfPresent(String.self, forKey: .answerText)
        answerJson = try? c.decodeIfPresent(AgentAnswerExtras.self, forKey: .answerJson)
        error = try c.decodeIfPresent(String.self, forKey: .error)
        expiresAt = try c.decodeIfPresent(String.self, forKey: .expiresAt)
    }

    var citations: [AgentCitation] { answerJson?.citations ?? [] }
    var expiry: Date? { AgentBridgeDate.parse(expiresAt) }
    var created: Date? { AgentBridgeDate.parse(createdAt) }
}

struct AgentRequestEnvelope: Decodable, Sendable {
    let request: AgentRequest
}

struct AgentRequestCreated: Decodable, Sendable {
    let request: AgentRequest
    let etaNote: String?

    enum CodingKeys: String, CodingKey {
        case request
        case etaNote = "eta_note"
    }
}

struct AgentRequestsResponse: Decodable, Sendable {
    let requests: [AgentRequest]
}

struct AskAgentBody: Encodable, Sendable {
    let question: String
    let conversationId: String?
    /// Small, user-visible context. The server rejects > 8000 bytes of JSON.
    let context: [String: String]

    enum CodingKeys: String, CodingKey {
        case question, context
        case conversationId = "conversation_id"
    }
}

// MARK: Agent keys

enum AgentScope: String, CaseIterable, Sendable, Identifiable {
    case readKnowledge = "read:knowledge"
    case writeFeed = "write:feed"
    case bridgeAnswer = "bridge:answer"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .readKnowledge: return "Read what you know"
        case .writeFeed: return "Suggest feed cards"
        case .bridgeAnswer: return "Answer your questions"
        }
    }

    var detail: String {
        switch self {
        case .readKnowledge: return "Concepts, mastery, due reviews and recent activity"
        case .writeFeed: return "Cards wait in your inbox until you approve them"
        case .bridgeAnswer: return "Pick up questions you hand off from chat"
        }
    }
}

struct AgentKey: Codable, Sendable, Identifiable, Hashable {
    let id: String
    let name: String
    let keyPrefix: String
    let scopes: [String]
    let createdAt: String?
    let lastUsedAt: String?
    let expiresAt: String?
    let revokedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, name, scopes
        case keyPrefix = "key_prefix"
        case createdAt = "created_at"
        case lastUsedAt = "last_used_at"
        case expiresAt = "expires_at"
        case revokedAt = "revoked_at"
    }

    init(id: String, name: String, keyPrefix: String, scopes: [String], createdAt: String? = nil,
         lastUsedAt: String? = nil, expiresAt: String? = nil, revokedAt: String? = nil) {
        self.id = id; self.name = name; self.keyPrefix = keyPrefix; self.scopes = scopes
        self.createdAt = createdAt; self.lastUsedAt = lastUsedAt; self.expiresAt = expiresAt
        self.revokedAt = revokedAt
    }

    var isRevoked: Bool { revokedAt != nil }
    var isExpired: Bool {
        guard let exp = AgentBridgeDate.parse(expiresAt) else { return false }
        return exp <= Date()
    }
    var isActive: Bool { !isRevoked && !isExpired }
    var lastUsed: Date? { AgentBridgeDate.parse(lastUsedAt) }
    var expiry: Date? { AgentBridgeDate.parse(expiresAt) }
}

struct AgentKeysResponse: Decodable, Sendable {
    let keys: [AgentKey]
}

struct CreateAgentKeyBody: Encodable, Sendable {
    let name: String
    let scopes: [String]
    let expiresInDays: Int?

    enum CodingKeys: String, CodingKey {
        case name, scopes
        case expiresInDays = "expires_in_days"
    }
}

/// `POST /keys` response. `apiKey` is the plaintext secret — shown once, never persisted.
struct CreatedAgentKey: Decodable, Sendable {
    let key: AgentKey
    let apiKey: String
    let warning: String?

    enum CodingKeys: String, CodingKey {
        case key, warning
        case apiKey = "api_key"
    }
}

struct RevokeAgentKeyResponse: Decodable, Sendable {
    let revoked: Bool
}

// MARK: - FeedItem helpers for `agent_curated`

extension FeedItem {
    var isAgentCurated: Bool { itemType == .agentCurated }

    /// `content.provenance.label` ("Curated by your agent"), with a fallback.
    var agentProvenanceLabel: String {
        if let prov = content["provenance"]?.value as? [String: Any],
           let label = prov["label"] as? String, !label.isEmpty {
            return label
        }
        return "From your agent"
    }

    var agentReason: String? { stringContent("reason") }
    var agentSummary: String? { stringContent("summary") }
    var agentSourceURL: URL? { AgentBridgeURL.safe(stringContent("source_url")) }
    var agentSourceKind: AgentSourceKind {
        AgentSourceKind(rawValue: stringContent("source_kind") ?? "") ?? .other
    }
    var agentFlashcard: AgentFlashcardBody? {
        guard let fc = content["flashcard"]?.value as? [String: Any],
              let front = fc["front"] as? String, let back = fc["back"] as? String
        else { return nil }
        return AgentFlashcardBody(front: front, back: back)
    }

    var substackPublicationName: String? { stringContent("publication_name") }
    var substackAuthor: String? { stringContent("author") }
    var substackExcerpt: String? { stringContent("excerpt_markdown") }
    var isSubstackIngested: Bool { (content["ingested"]?.value as? Bool) ?? false }

    struct MatchedGraphConcept: Identifiable, Hashable {
        let id: String
        let name: String
        let state: String
    }

    var substackMatchedConcepts: [MatchedGraphConcept] {
        guard let raw = content["matched_concepts"]?.value as? [[String: Any]] else { return [] }
        return raw.compactMap { entry in
            guard let id = entry["id"] as? String,
                  let name = entry["name"] as? String, !name.isEmpty
            else { return nil }
            let state = (entry["state"] as? String) ?? "seen"
            return MatchedGraphConcept(id: id, name: name, state: state)
        }
    }
}

// MARK: - Mock data (previews + demo mode)

enum AgentBridgeMocks {
    static let pendingItems: [AgentFeedItem] = [
        AgentFeedItem(
            id: "mock-agent-1",
            title: "Attention is a soft dictionary lookup",
            summary: "A 6-minute read that rebuilds scaled dot-product attention from key/value retrieval, with the √d scaling motivated by variance.",
            reason: "Your mastery of Self-Attention is 0.41 and your ML exam is on Friday.",
            sourceUrl: "https://example.substack.com/p/attention-lookup",
            sourceKind: .substack,
            conceptIds: ["c-attention"],
            targetDate: "2026-11-25",
            createdAt: "2026-11-24T22:10:04.120000+00:00"
        ),
        AgentFeedItem(
            id: "mock-agent-2",
            itemKind: "exam_prep",
            title: "Exam prep: SM-2 interval math",
            summary: "Three worked examples of how the ease factor moves after Again/Hard/Good.",
            reason: "An email from your course said Quiz 3 covers spaced repetition.",
            sourceKind: .email,
            targetDate: "2026-11-25"
        ),
        AgentFeedItem(
            id: "mock-agent-3",
            itemKind: "flashcard",
            title: "Graph RAG vs. vector RAG",
            summary: "When multi-hop questions need explicit relationships.",
            reason: "You saved two notes on GraphRAG this week.",
            sourceUrl: "https://example.com/graph-rag",
            sourceKind: .web,
            targetDate: "2026-11-25",
            bodyJson: AgentFeedItemBody(flashcard: AgentFlashcardBody(
                front: "Why does Graph RAG help multi-hop questions?",
                back: "It retrieves along explicit edges, so evidence chains are kept instead of lost to top-k similarity."
            ))
        ),
    ]

    static let curatedFeedItem = FeedItem(
        id: "agent:mock-agent-1",
        itemType: .agentCurated,
        content: [
            "title": AnyCodable("Attention is a soft dictionary lookup"),
            "summary": AnyCodable("Rebuilds scaled dot-product attention from key/value retrieval."),
            "reason": AnyCodable("Your mastery of Self-Attention is 0.41 and your ML exam is on Friday."),
            "source_url": AnyCodable("https://example.substack.com/p/attention-lookup"),
            "source_kind": AnyCodable("substack"),
            "item_kind": AnyCodable("article"),
            "provenance": AnyCodable(["curated_by": "agent", "label": "Curated by your agent"]),
        ],
        conceptId: "c-attention",
        priorityScore: 1.5
    )

    static let answered = AgentRequest(
        id: "mock-req-1",
        status: .answered,
        question: "How does LoRA rank affect what the adapter can learn?",
        createdAt: "2026-11-24T10:02:11.000000+00:00",
        answeredAt: "2026-11-24T10:06:40.000000+00:00",
        answerText: "**Short version:** rank caps the dimension of the update ΔW = BA. Low rank (4–8) is enough for style/format shifts; new factual or domain knowledge usually needs higher rank or full fine-tuning.\n\nYou already know *matrix rank* well (mastery 0.82), so think of it as the number of independent directions the adapter can move the weights in. [This link is stripped](javascript:alert(1)); [this one stays](https://arxiv.org/abs/2106.09685).",
        answerJson: AgentAnswerExtras(citations: [
            AgentCitation(title: "LoRA paper (Hu et al.)", url: "https://arxiv.org/abs/2106.09685"),
            AgentCitation(title: "Unsafe link (ignored)", url: "javascript:alert(1)"),
        ])
    )

    static let researching = AgentRequest(
        id: "mock-req-2", status: .claimed,
        question: "Compare GraphRAG community summaries with RAPTOR trees.",
        createdAt: "2026-11-24T10:12:00+00:00"
    )

    static let failed = AgentRequest(
        id: "mock-req-3", status: .failed,
        question: "What did my professor say about the midterm?",
        error: "No matching email in the last 14 days."
    )

    static let keys: [AgentKey] = [
        AgentKey(id: "k1", name: "Grok Bot", keyPrefix: "grk_ab12cd34",
                 scopes: AgentScope.allCases.map(\.rawValue),
                 createdAt: "2026-11-20T08:00:00+00:00",
                 lastUsedAt: "2026-11-24T02:30:00+00:00",
                 expiresAt: "2027-02-18T08:00:00+00:00"),
        AgentKey(id: "k2", name: "Old laptop script", keyPrefix: "grk_99ff0011",
                 scopes: ["read:knowledge"],
                 createdAt: "2026-09-01T08:00:00+00:00",
                 revokedAt: "2026-10-01T08:00:00+00:00"),
    ]
}

// MARK: - Errors (PR #3 @ cadf9c8 status codes)

/// Friendly copy for agent-bridge failures. Server bodies are FastAPI `{"detail": "..."}`.
///
/// | code | where | meaning |
/// |---|---|---|
/// | 400 | any id route, `status=` filter | malformed UUID / unknown status |
/// | 404 | any | not found / not yours / bridge disabled; `conversation_id` not owned on POST /requests |
/// | 409 | approve/reject | invalid transition (already handled) · POST /keys: 5 active keys |
/// | 413 | POST /requests | context > 8 KB |
/// | 429 | POST /requests | per-user hourly quota (`Retry-After: 600`) |
/// | 503 | POST /keys | server has no `AGENT_KEY_PEPPER` (fails closed) |
enum AgentBridgeAction: Sendable {
    case ask, approve, reject, createKey, revokeKey, load
}

enum AgentBridgeErrorCopy {
    /// `detail` from a FastAPI error body, if any.
    static func detail(_ error: Error) -> String? {
        guard case let APIError.http(_, body) = error,
              let data = body.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return obj["detail"] as? String
    }

    static func statusCode(_ error: Error) -> Int? {
        if case let APIError.http(code, _) = error { return code }
        return nil
    }

    static func isRateLimited(_ error: Error) -> Bool { statusCode(error) == 429 }

    /// True for the "conversation not found" 404 on POST /requests (retry without it).
    static func isConversationNotFound(_ error: Error) -> Bool {
        statusCode(error) == 404 && (detail(error)?.localizedCaseInsensitiveContains("conversation") ?? false)
    }

    static func message(_ error: Error, action: AgentBridgeAction) -> String {
        let detail = detail(error)?.lowercased() ?? ""
        switch (statusCode(error), action) {
        case (429, _):
            return "You\u{2019}ve sent your agent a lot of questions this hour. Try again in about 10 minutes."
        case (_, _) where detail.contains("daily") && (detail.contains("cap") || detail.contains("limit")):
            return "Your agent hit today\u{2019}s limit. It can send more tomorrow."
        case (409, .approve), (409, .reject):
            return "Already handled \u{2014} this suggestion was approved or dismissed elsewhere."
        case (409, .createKey):
            return "You already have 5 active keys. Revoke one first."
        case (503, .createKey):
            return "Agent keys aren\u{2019}t set up on this server yet."
        case (413, .ask):
            return "That question has too much attached context. Try a shorter one."
        case (400, _):
            return "GraphRecall couldn\u{2019}t read that request. Update the app and try again."
        case (404, .ask):
            return "Your agent isn\u{2019}t available on this server."
        case (404, _):
            return "That item no longer exists."
        default:
            return APIError.userFacing(error, resource: "agent")
        }
    }
}

// MARK: - Audit log (GET /api/agent-bridge/audit)

/// Metadata-only record of what an agent (or the user) did through the bridge.
struct AgentAuditEvent: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let actor: String
    let action: String
    let tool: String?
    let keyId: String?
    let targetId: String?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, actor, action, tool
        case keyId = "key_id"
        case targetId = "target_id"
        case createdAt = "created_at"
    }

    var created: Date? { AgentBridgeDate.parse(createdAt) }
}

struct AgentAuditResponse: Decodable, Sendable {
    let events: [AgentAuditEvent]
}
