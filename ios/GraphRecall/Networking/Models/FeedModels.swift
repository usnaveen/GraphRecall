import Foundation

enum FeedItemType: String, Codable, Hashable, Sendable {
    case flashcard
    case mcq
    case fillBlank = "fill_blank"
    case infographic
    case diagram
    case screenshot
    case showcase
    case codeChallenge = "code_challenge"
    case codeSandbox = "code_sandbox"
    case territory
    case spotTheBug = "spot_the_bug"
    case tradeoffDuel = "tradeoff_duel"
    case diagramOcclusion = "diagram_occlusion"
    /// Curated by the user's external agent (agent bridge, PR #3). Pending items never reach
    /// `/api/feed`; only ones the user approved in the inbox.
    case agentCurated = "agent_curated"
    /// A wire type this build doesn't know (e.g. added server-side later). Hidden from the feed
    /// rather than mis-rendered as a blank Term Card. Never sent back to the server.
    case unknown

    /// Accept backend wire values *and* web CardType aliases (`quiz`, `fillblank`, etc.).
    /// Unrecognised values decode as `.unknown` (hidden), not as a flashcard.
    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = FeedItemType.parseKnown(raw) ?? .unknown
    }

    /// Lenient mapping for locally generated cards (chat create-card, concept dump), where a
    /// missing/odd type really is a term card.
    static func parse(_ raw: String) -> FeedItemType {
        parseKnown(raw) ?? .flashcard
    }

    static func parseKnown(_ raw: String) -> FeedItemType? {
        switch raw.lowercased() {
        case "flashcard", "term_card": return .flashcard
        case "mcq", "quiz": return .mcq
        case "fill_blank", "fillblank": return .fillBlank
        case "infographic": return .infographic
        case "diagram": return .diagram
        case "screenshot": return .screenshot
        case "showcase", "concept_showcase": return .showcase
        case "code_challenge": return .codeChallenge
        case "code_sandbox": return .codeSandbox
        case "territory": return .territory
        case "spot_the_bug": return .spotTheBug
        case "tradeoff_duel": return .tradeoffDuel
        case "diagram_occlusion": return .diagramOcclusion
        case "agent_curated": return .agentCurated
        default: return nil
        }
    }

    var displayLabel: String {
        switch self {
        case .flashcard: return "Term Card"
        case .mcq: return "Quiz"
        case .fillBlank: return "Fill in the Blank"
        case .infographic: return "Infographic"
        case .diagram: return "Diagram"
        case .screenshot: return "Screenshot"
        case .showcase: return "Concept Showcase"
        case .codeChallenge: return "Code Challenge"
        case .codeSandbox: return "Code Sandbox"
        case .territory: return "Map the Territory"
        case .spotTheBug: return "Spot the Bug"
        case .tradeoffDuel: return "Tradeoff Duel"
        case .diagramOcclusion: return "Diagram Check"
        case .agentCurated: return "From your agent"
        case .unknown: return "Card"
        }
    }

    var accentColorName: String {
        switch self {
        case .flashcard, .showcase: return "accent"
        case .mcq: return "accent"
        case .fillBlank, .codeChallenge, .codeSandbox, .territory, .spotTheBug: return "cyan"
        case .diagram, .tradeoffDuel, .diagramOcclusion: return "purple"
        case .screenshot, .infographic: return "coral"
        case .agentCurated: return "cyan"
        case .unknown: return "accent"
        }
    }
}

enum ReviewDifficulty: String, Codable, CaseIterable, Identifiable, Sendable {
    case again, hard, good, easy
    var id: String { rawValue }

    var label: String {
        switch self {
        case .again: return "Again"
        case .hard: return "Hard"
        case .good: return "Good"
        case .easy: return "Easy"
        }
    }

    /// SM-2 quality mapping used locally when offline (0–5 scale).
    var sm2Quality: Int {
        switch self {
        case .again: return 1
        case .hard: return 3
        case .good: return 4
        case .easy: return 5
        }
    }
}

struct FeedResponse: Codable, Sendable {
    let items: [FeedItem]
    let totalDueToday: Int
    let completedToday: Int
    let dailyGoal: Int
    let streakDays: Int
    let domains: [String]
    let activeConceptsToday: Int
    let dailyConceptCap: Int
    let conceptsShownToday: [String]

    enum CodingKeys: String, CodingKey {
        case items
        case totalDueToday = "total_due_today"
        case completedToday = "completed_today"
        case dailyGoal = "daily_goal"
        case streakDays = "streak_days"
        case domains
        case activeConceptsToday = "active_concepts_today"
        case dailyConceptCap = "daily_concept_cap"
        case conceptsShownToday = "concepts_shown_today"
    }

    init(
        items: [FeedItem] = [],
        totalDueToday: Int = 0,
        completedToday: Int = 0,
        dailyGoal: Int = 20,
        streakDays: Int = 0,
        domains: [String] = [],
        activeConceptsToday: Int = 0,
        dailyConceptCap: Int = 7,
        conceptsShownToday: [String] = []
    ) {
        self.items = items
        self.totalDueToday = totalDueToday
        self.completedToday = completedToday
        self.dailyGoal = dailyGoal
        self.streakDays = streakDays
        self.domains = domains
        self.activeConceptsToday = activeConceptsToday
        self.dailyConceptCap = dailyConceptCap
        self.conceptsShownToday = conceptsShownToday
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        items = try c.decodeIfPresent([FeedItem].self, forKey: .items) ?? []
        totalDueToday = try c.decodeIfPresent(Int.self, forKey: .totalDueToday) ?? 0
        completedToday = try c.decodeIfPresent(Int.self, forKey: .completedToday) ?? 0
        dailyGoal = try c.decodeIfPresent(Int.self, forKey: .dailyGoal) ?? 20
        streakDays = try c.decodeIfPresent(Int.self, forKey: .streakDays) ?? 0
        domains = try c.decodeIfPresent([String].self, forKey: .domains) ?? []
        activeConceptsToday = try c.decodeIfPresent(Int.self, forKey: .activeConceptsToday) ?? 0
        dailyConceptCap = try c.decodeIfPresent(Int.self, forKey: .dailyConceptCap) ?? 7
        conceptsShownToday = try c.decodeIfPresent([String].self, forKey: .conceptsShownToday) ?? []
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(items, forKey: .items)
        try c.encode(totalDueToday, forKey: .totalDueToday)
        try c.encode(completedToday, forKey: .completedToday)
        try c.encode(dailyGoal, forKey: .dailyGoal)
        try c.encode(streakDays, forKey: .streakDays)
        try c.encode(domains, forKey: .domains)
        try c.encode(activeConceptsToday, forKey: .activeConceptsToday)
        try c.encode(dailyConceptCap, forKey: .dailyConceptCap)
        try c.encode(conceptsShownToday, forKey: .conceptsShownToday)
    }
}

struct FeedMCQOption: Hashable, Sendable, Identifiable {
    let id: String
    let text: String
    let isCorrect: Bool
}

struct FeedItem: Codable, Sendable, Identifiable, Hashable {
    let id: String
    let itemType: FeedItemType
    let content: [String: AnyCodable]
    let conceptId: String?
    let conceptName: String?
    let domain: String?
    let priorityScore: Double?
    let dueDate: Date?

    init(
        id: String,
        itemType: FeedItemType,
        content: [String: AnyCodable] = [:],
        conceptId: String? = nil,
        conceptName: String? = nil,
        domain: String? = nil,
        priorityScore: Double? = nil,
        dueDate: Date? = nil
    ) {
        self.id = id
        self.itemType = itemType
        self.content = content
        self.conceptId = conceptId
        self.conceptName = conceptName
        self.domain = domain
        self.priorityScore = priorityScore
        self.dueDate = dueDate
    }

    enum CodingKeys: String, CodingKey {
        case id
        case itemType = "item_type"
        case content
        case conceptId = "concept_id"
        case conceptName = "concept_name"
        case domain
        case priorityScore = "priority_score"
        case dueDate = "due_date"
    }

    var isDemo: Bool {
        id.hasPrefix("demo-") || domain?.caseInsensitiveCompare("Demo") == .orderedSame
    }

    /// True only for cards that hide an answer or require an explicit check step before grading.
    /// Open reading cards (`showcase`, `diagram`, `screenshot`, `infographic`, plain `agentCurated`)
    /// show all of their content upfront and never need a "Continue" button.
    var requiresExplicitReveal: Bool {
        switch itemType {
        case .showcase, .diagram, .screenshot, .infographic, .unknown:
            return false
        case .agentCurated:
            return agentFlashcard != nil
        case .flashcard, .mcq, .fillBlank, .codeChallenge, .codeSandbox,
             .territory, .spotTheBug, .tradeoffDuel, .diagramOcclusion:
            return true
        }
    }

    /// Passive showcase / upload cards and `revisit-*` padding cards have no test prompt to grade.
    var usesRecallGrading: Bool {
        if id.hasPrefix("revisit-") || isAgentCurated { return false }
        switch itemType {
        case .showcase, .screenshot, .infographic, .diagram, .agentCurated, .unknown:
            return false
        default:
            return true
        }
    }

    var title: String {
        if let name = conceptName, !name.isEmpty { return name }
        if let front = stringContent("front") { return front }
        if let q = stringContent("question") { return q }
        if let t = stringContent("title") { return t }
        return itemType.displayLabel
    }

    var prompt: String {
        stringContent("front")
            ?? stringContent("question")
            ?? stringContent("sentence")
            ?? stringContent("instruction")
            ?? stringContent("description")
            ?? stringContent("definition")
            ?? stringContent("prompt")
            ?? stringContent("scenario")
            ?? title
    }

    var answer: String? {
        stringContent("back")
            ?? stringContent("explanation")
            ?? stringContent("solution_code")
            ?? stringContent("solutionCode")
            ?? firstAnswerFromList()
    }

    func stringContent(_ key: String) -> String? {
        guard let v = content[key]?.value as? String, !v.isEmpty else { return nil }
        return v
    }

    func stringArrayContent(_ key: String) -> [String] {
        if let arr = content[key]?.value as? [String] { return arr }
        if let arr = content[key]?.value as? [Any] {
            return arr.compactMap { $0 as? String }
        }
        return []
    }

    func firstAnswerFromList() -> String? {
        let answers = stringArrayContent("answers")
        if let first = answers.first { return first }
        return stringContent("answer")
    }

    var mcqOptions: [FeedMCQOption] {
        guard let raw = content["options"]?.value else { return [] }

        if let strings = raw as? [String] {
            let correct = stringContent("correct_answer")
            return strings.enumerated().map { idx, text in
                FeedMCQOption(
                    id: "opt-\(idx)",
                    text: text,
                    isCorrect: correct.map { $0 == text } ?? false
                )
            }
        }

        if let dicts = raw as? [[String: Any]] {
            return dicts.enumerated().map { idx, d in
                let text = (d["text"] as? String) ?? (d["label"] as? String) ?? "Option \(idx + 1)"
                let id = (d["id"] as? String) ?? "opt-\(idx)"
                let isCorrect = (d["is_correct"] as? Bool)
                    ?? (d["isCorrect"] as? Bool)
                    ?? false
                return FeedMCQOption(id: id, text: text, isCorrect: isCorrect)
            }
        }

        if let boxed = raw as? [Any] {
            return boxed.enumerated().compactMap { idx, el -> FeedMCQOption? in
                if let s = el as? String {
                    let correct = stringContent("correct_answer")
                    return FeedMCQOption(id: "opt-\(idx)", text: s, isCorrect: correct == s)
                }
                if let d = el as? [String: Any] {
                    let text = (d["text"] as? String) ?? "Option \(idx + 1)"
                    let id = (d["id"] as? String) ?? "opt-\(idx)"
                    let isCorrect = (d["is_correct"] as? Bool) ?? (d["isCorrect"] as? Bool) ?? false
                    return FeedMCQOption(id: id, text: text, isCorrect: isCorrect)
                }
                return nil
            }
        }
        return []
    }

    var imageURL: URL? {
        let s = stringContent("file_url")
            ?? stringContent("imageUrl")
            ?? stringContent("thumbnail_url")
            ?? stringContent("thumbnailUrl")
        guard let s, let url = URL(string: s) else { return nil }
        return url
    }


    /// Backend `item_type` for like/save POSTs. Nil when the API does not support the type.
    var likeSaveAPIItemType: String? {
        switch itemType {
        case .flashcard: return "flashcard"
        case .mcq: return "mcq"
        case .fillBlank: return "fill_blank"
        default: return nil
        }
    }

    /// Plain-text share payload (front/back or question) — v1 ShareLink / activity sheet.
    var sharePlainText: String {
        var lines: [String] = ["GraphRecall · \(itemType.displayLabel)"]
        if let name = conceptName, !name.isEmpty {
            lines.append(name)
        }
        let body = prompt
        if !body.isEmpty { lines.append(body) }
        if let answer, !answer.isEmpty {
            lines.append("")
            lines.append(answer)
        }
        return lines.joined(separator: "\n")
    }

    var linkedConcepts: [String] {
        stringArrayContent("linked_concepts").isEmpty
            ? stringArrayContent("linkedConcepts")
            : stringArrayContent("linked_concepts")
    }

    var keyPoints: [String] {
        let a = stringArrayContent("key_points")
        return a.isEmpty ? stringArrayContent("keyPoints") : a
    }

    /// Decoded payload for `code_sandbox` feed cards (`backend/services/code_sandbox_cards.py`).
    var sandboxPayload: SandboxChallengePayload {
        let fallbackId = id.hasPrefix("code_sandbox:")
            ? String(id.dropFirst("code_sandbox:".count))
            : id
        let challengeId = stringContent("challenge_id")
            ?? stringContent("challengeId")
            ?? fallbackId
        let title = stringContent("title") ?? conceptName ?? "Code Sandbox"
        let promptText = stringContent("prompt")
            ?? stringContent("instruction")
            ?? prompt
        let language = stringContent("language") ?? "javascript"
        let starterCode = stringContent("starter_code")
            ?? stringContent("starterCode")
            ?? stringContent("initial_code")
            ?? ""
        let solutionCode = stringContent("solution_code")
            ?? stringContent("solutionCode")
        let hint = stringContent("hint")
        let difficulty = stringContent("difficulty") ?? "medium"

        let rawTests: [[String: Any]]
        if let typed = content["test_cases"]?.value as? [[String: Any]] {
            rawTests = typed
        } else if let typed = content["testCases"]?.value as? [[String: Any]] {
            rawTests = typed
        } else if let boxed = (content["test_cases"]?.value as? [Any]) ?? (content["testCases"]?.value as? [Any]) {
            rawTests = boxed.compactMap { $0 as? [String: Any] }
        } else {
            rawTests = []
        }

        let testCases = rawTests.compactMap { dict -> SandboxTestCase? in
            guard let name = dict["name"] as? String,
                  let expression = dict["expression"] as? String else { return nil }
            let expected = (dict["expected_repr"] as? String)
                ?? (dict["expectedRepr"] as? String)
                ?? "null"
            return SandboxTestCase(name: name, expression: expression, expectedRepr: expected)
        }

        return SandboxChallengePayload(
            challengeId: challengeId,
            title: title,
            prompt: promptText,
            language: language,
            starterCode: starterCode,
            solutionCode: solutionCode,
            hint: hint,
            difficulty: difficulty,
            testCases: testCases
        )
    }

    /// Decoded payload for `spot_the_bug` feed cards (`backend/services/creative_cards.py`).
    var spotTheBugPayload: SpotTheBugPayload {
        let rawCardId = stringContent("card_id")
            ?? stringContent("cardId")
            ?? stringContent("id")
            ?? id
        let cardId = rawCardId.hasPrefix("spot_the_bug:")
            ? String(rawCardId.dropFirst("spot_the_bug:".count))
            : rawCardId

        let title = stringContent("title") ?? conceptName ?? "Spot the Bug"
        let language = stringContent("language") ?? "python"

        var parsedLines = stringArrayContent("lines")
        if parsedLines.isEmpty, let codeBlock = stringContent("code") ?? stringContent("initial_code") {
            parsedLines = codeBlock
                .replacingOccurrences(of: "\r\n", with: "\n")
                .components(separatedBy: "\n")
        }
        if parsedLines.isEmpty {
            parsedLines = ["# Inspect snippet"]
        }

        let rawBugIndex: Int = {
            if let v = content["buggy_line_index"]?.value as? Int { return v }
            if let v = content["buggyLineIndex"]?.value as? Int { return v }
            if let d = content["buggy_line_index"]?.value as? Double { return Int(d) }
            if let s = stringContent("buggy_line_index"), let parsed = Int(s) { return parsed }
            return 1
        }()
        let safeBugIndex = min(max(rawBugIndex, 1), parsedLines.count)

        let explanation = stringContent("explanation")
            ?? "Review why this line introduces a subtle bug in production."
        let fixedLine = stringContent("fixed_line")
            ?? stringContent("fixedLine")
            ?? ""
        let resolvedConcept = stringContent("concept_name")
            ?? stringContent("conceptName")
            ?? conceptName
            ?? title
        let tags = stringArrayContent("tags")

        return SpotTheBugPayload(
            cardId: cardId,
            title: title,
            language: language,
            lines: parsedLines,
            buggyLineIndex: safeBugIndex,
            explanation: explanation,
            fixedLine: fixedLine,
            conceptName: resolvedConcept,
            tags: tags
        )
    }

    /// Decoded payload for `tradeoff_duel` feed cards (`backend/services/creative_cards.py`).
    var tradeoffDuelPayload: TradeoffDuelPayload {
        let rawCardId = stringContent("card_id")
            ?? stringContent("cardId")
            ?? stringContent("id")
            ?? id
        let cardId = rawCardId.hasPrefix("tradeoff_duel:")
            ? String(rawCardId.dropFirst("tradeoff_duel:".count))
            : rawCardId

        let title = stringContent("title") ?? conceptName ?? "Tradeoff Duel"
        let scenario = stringContent("scenario")
            ?? stringContent("prompt")
            ?? "Compare both architectural approaches for this workload."
        let optionA = stringContent("option_a")
            ?? stringContent("optionA")
            ?? "Option A"
        let optionB = stringContent("option_b")
            ?? stringContent("optionB")
            ?? "Option B"

        let rawRec = (stringContent("recommended") ?? "a")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        let recommended: String
        switch rawRec {
        case "a", "b", "depends":
            recommended = rawRec
        default:
            recommended = "depends"
        }

        let winningRationale = stringContent("winning_rationale")
            ?? stringContent("winningRationale")
            ?? stringContent("explanation")
            ?? "Compare latency, operational complexity, and consistency guarantees."
        let whenOtherWins = stringContent("when_other_wins")
            ?? stringContent("whenOtherWins")
            ?? ""
        let resolvedConcept = stringContent("concept_name")
            ?? stringContent("conceptName")
            ?? conceptName
            ?? title
        let tags = stringArrayContent("tags")

        return TradeoffDuelPayload(
            cardId: cardId,
            title: title,
            scenario: scenario,
            optionA: optionA,
            optionB: optionB,
            recommended: recommended,
            winningRationale: winningRationale,
            whenOtherWins: whenOtherWins,
            conceptName: resolvedConcept,
            tags: tags
        )
    }

    /// Decoded payload for `diagram_occlusion` feed cards (`backend/services/creative_cards.py`).
    var diagramOcclusionPayload: DiagramOcclusionPayload {
        let rawCardId = stringContent("card_id")
            ?? stringContent("cardId")
            ?? stringContent("id")
            ?? id
        let cardId = rawCardId.hasPrefix("diagram_occlusion:")
            ? String(rawCardId.dropFirst("diagram_occlusion:".count))
            : rawCardId

        let title = stringContent("title") ?? conceptName ?? "Diagram Check"
        let sourceTitle = stringContent("source_title") ?? stringContent("sourceTitle") ?? ""
        let safeSourceURL = Self.validatedHTTPURL(
            stringContent("source_url") ?? stringContent("sourceUrl")
        )
        let originalMermaid = stringContent("original_mermaid") ?? stringContent("originalMermaid")
        let occludedMermaid = stringContent("occluded_mermaid")
            ?? stringContent("occludedMermaid")
            ?? stringContent("mermaid_code")

        let safeImageURL = Self.validatedHTTPURL(
            stringContent("image_url")
                ?? stringContent("imageUrl")
                ?? stringContent("file_url")
        )
        let caption = stringContent("caption")

        let rawKind = stringContent("kind")?.lowercased()
        let kind: String
        if let rawKind, rawKind == "figure" || rawKind == "mermaid" {
            kind = rawKind
        } else if safeImageURL != nil && occludedMermaid == nil {
            kind = "figure"
        } else {
            kind = "mermaid"
        }

        var answerKey: [String: String] = [:]
        let rawAnswerObj = content["answer_key"]?.value ?? content["answerKey"]?.value
        if let typed = rawAnswerObj as? [String: String] {
            answerKey = typed
        } else if let generic = rawAnswerObj as? [String: Any] {
            for (k, v) in generic {
                if let strVal = v as? String, !strVal.isEmpty {
                    answerKey[k] = strVal
                }
            }
        }

        let distractors = stringArrayContent("distractors")
        var options = stringArrayContent("options")
        if options.isEmpty && kind == "mermaid" {
            let answerValues = DiagramOcclusionPayload.sortSlotKeys(Array(answerKey.keys))
                .compactMap { answerKey[$0] }
            var seen = Set<String>()
            for candidate in answerValues + distractors {
                let key = candidate.lowercased()
                if !seen.contains(key) {
                    seen.insert(key)
                    options.append(candidate)
                }
            }
        }

        let promptText = stringContent("prompt")
            ?? (kind == "figure"
                ? "Explain the architecture and key takeaway shown in this figure."
                : "Recall the occluded component(s) in this diagram.")

        return DiagramOcclusionPayload(
            cardId: cardId,
            kind: kind,
            title: title,
            prompt: promptText,
            sourceTitle: sourceTitle,
            sourceURL: safeSourceURL,
            originalMermaid: originalMermaid,
            occludedMermaid: occludedMermaid,
            answerKey: answerKey,
            distractors: distractors,
            options: options,
            imageURL: safeImageURL,
            caption: caption
        )
    }

    private static func validatedHTTPURL(_ raw: String?) -> URL? {
        guard let raw else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              !trimmed.contains(where: { $0.isWhitespace }),
              let url = URL(string: trimmed),
              let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              let host = url.host,
              !host.isEmpty else {
            return nil
        }
        return url
    }
}

struct SpotTheBugPayload: Hashable, Sendable {
    let cardId: String
    let title: String
    let language: String
    let lines: [String]
    let buggyLineIndex: Int
    let explanation: String
    let fixedLine: String
    let conceptName: String
    let tags: [String]
}

struct SpotTheBugGradeResponse: Decodable, Sendable {
    let correct: Bool
    let selectedLine: Int?
    let buggyLineIndex: Int?
    let explanation: String?
    let fixedLine: String?
    let cardId: String?
    let conceptName: String?
    let conceptId: String?
    let recorded: Bool?

    enum CodingKeys: String, CodingKey {
        case correct
        case selectedLine = "selected_line"
        case buggyLineIndex = "buggy_line_index"
        case explanation
        case fixedLine = "fixed_line"
        case cardId = "card_id"
        case conceptName = "concept_name"
        case conceptId = "concept_id"
        case recorded
    }
}

struct TradeoffDuelPayload: Hashable, Sendable {
    let cardId: String
    let title: String
    let scenario: String
    let optionA: String
    let optionB: String
    /// `"a"` | `"b"` | `"depends"`
    let recommended: String
    let winningRationale: String
    let whenOtherWins: String
    let conceptName: String
    let tags: [String]
}

struct DiagramOcclusionPayload: Hashable, Sendable {
    let cardId: String
    /// `"mermaid"` | `"figure"`
    let kind: String
    let title: String
    let prompt: String
    let sourceTitle: String
    let sourceURL: URL?
    let originalMermaid: String?
    let occludedMermaid: String?
    let answerKey: [String: String]
    let distractors: [String]
    let options: [String]
    let imageURL: URL?
    let caption: String?

    var isFigure: Bool {
        kind == "figure" || (imageURL != nil && occludedMermaid == nil)
    }

    /// Ordered slot keys (`SLOT_1`, `SLOT_2`, ...) for Mermaid occlusion cards.
    var orderedSlots: [String] {
        let nonTakeawayKeys = answerKey.keys.filter { $0.lowercased() != "takeaway" }
        if !nonTakeawayKeys.isEmpty {
            return Self.sortSlotKeys(Array(nonTakeawayKeys))
        }
        guard let occludedMermaid,
              let regex = try? NSRegularExpression(pattern: #"\[(SLOT_\d+)\]"#) else {
            return []
        }
        let nsRange = NSRange(occludedMermaid.startIndex..<occludedMermaid.endIndex, in: occludedMermaid)
        var discovered: [String] = []
        regex.enumerateMatches(in: occludedMermaid, options: [], range: nsRange) { match, _, _ in
            guard let match, let r = Range(match.range(at: 1), in: occludedMermaid) else { return }
            let slot = String(occludedMermaid[r])
            if !discovered.contains(slot) {
                discovered.append(slot)
            }
        }
        return Self.sortSlotKeys(discovered)
    }

    static func sortSlotKeys(_ keys: [String]) -> [String] {
        keys.sorted { lhs, rhs in
            let lNum = Int(lhs.replacingOccurrences(of: "SLOT_", with: "")) ?? Int.max
            let rNum = Int(rhs.replacingOccurrences(of: "SLOT_", with: "")) ?? Int.max
            if lNum != rNum { return lNum < rNum }
            return lhs < rhs
        }
    }
}

struct SandboxChallengePayload: Hashable, Sendable {
    let challengeId: String
    let title: String
    let prompt: String
    let language: String
    let starterCode: String
    let solutionCode: String?
    let hint: String?
    let difficulty: String
    let testCases: [SandboxTestCase]
}

struct SandboxResultResponse: Decodable, Sendable {
    let recorded: Bool
    let signal: Double?
    let result: String?
    let conceptId: String?

    enum CodingKeys: String, CodingKey {
        case recorded, signal, result
        case conceptId = "concept_id"
    }
}

/// Type-erased JSON value for feed content blobs.
struct AnyCodable: Codable, @unchecked Sendable, Hashable {
    let value: Any

    init(_ value: Any) { self.value = value }

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { value = NSNull(); return }
        if let b = try? c.decode(Bool.self) { value = b; return }
        if let i = try? c.decode(Int.self) { value = i; return }
        if let d = try? c.decode(Double.self) { value = d; return }
        if let s = try? c.decode(String.self) { value = s; return }
        if let a = try? c.decode([AnyCodable].self) { value = a.map(\.value); return }
        if let o = try? c.decode([String: AnyCodable].self) {
            value = o.mapValues(\.value); return
        }
        value = NSNull()
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch value {
        case is NSNull: try c.encodeNil()
        case let b as Bool: try c.encode(b)
        case let i as Int: try c.encode(i)
        case let d as Double: try c.encode(d)
        case let s as String: try c.encode(s)
        case let a as [Any]: try c.encode(a.map { AnyCodable($0) })
        case let o as [String: Any]: try c.encode(o.mapValues { AnyCodable($0) })
        default: try c.encodeNil()
        }
    }

    static func == (lhs: AnyCodable, rhs: AnyCodable) -> Bool {
        String(describing: lhs.value) == String(describing: rhs.value)
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(String(describing: value))
    }
}

struct DailyActivity: Codable, Sendable, Hashable {
    let date: String
    let reviewsCompleted: Int
    let conceptsLearned: Int
    let notesAdded: Int
    let accuracy: Double

    enum CodingKeys: String, CodingKey {
        case date
        case reviewsCompleted = "reviews_completed"
        case conceptsLearned = "concepts_learned"
        case notesAdded = "notes_added"
        case accuracy
    }

    init(
        date: String,
        reviewsCompleted: Int = 0,
        conceptsLearned: Int = 0,
        notesAdded: Int = 0,
        accuracy: Double = 0
    ) {
        self.date = date
        self.reviewsCompleted = reviewsCompleted
        self.conceptsLearned = conceptsLearned
        self.notesAdded = notesAdded
        self.accuracy = accuracy
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = try c.decode(String.self, forKey: .date)
        reviewsCompleted = try c.decodeIfPresent(Int.self, forKey: .reviewsCompleted) ?? 0
        conceptsLearned = try c.decodeIfPresent(Int.self, forKey: .conceptsLearned) ?? 0
        notesAdded = try c.decodeIfPresent(Int.self, forKey: .notesAdded) ?? 0
        accuracy = try c.decodeIfPresent(Double.self, forKey: .accuracy) ?? 0
    }
}

struct UserStats: Codable, Sendable {
    let userId: String?
    let totalConcepts: Int?
    let totalNotes: Int?
    let totalReviews: Int?
    let streakDays: Int?
    let accuracyRate: Double?
    let dueToday: Int?
    let completedToday: Int?
    let dailyGoal: Int?
    let overdue: Int?
    let dailyActivity: [DailyActivity]

    enum CodingKeys: String, CodingKey {
        case userId = "user_id"
        case totalConcepts = "total_concepts"
        case totalNotes = "total_notes"
        case totalReviews = "total_reviews"
        case streakDays = "streak_days"
        case accuracyRate = "accuracy_rate"
        case dueToday = "due_today"
        case completedToday = "completed_today"
        case dailyGoal = "daily_goal"
        case overdue
        case dailyActivity = "daily_activity"
    }

    init(
        userId: String? = nil,
        totalConcepts: Int? = nil,
        totalNotes: Int? = nil,
        totalReviews: Int? = nil,
        streakDays: Int? = nil,
        accuracyRate: Double? = nil,
        dueToday: Int? = nil,
        completedToday: Int? = nil,
        dailyGoal: Int? = nil,
        overdue: Int? = nil,
        dailyActivity: [DailyActivity] = []
    ) {
        self.userId = userId
        self.totalConcepts = totalConcepts
        self.totalNotes = totalNotes
        self.totalReviews = totalReviews
        self.streakDays = streakDays
        self.accuracyRate = accuracyRate
        self.dueToday = dueToday
        self.completedToday = completedToday
        self.dailyGoal = dailyGoal
        self.overdue = overdue
        self.dailyActivity = dailyActivity
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        userId = try c.decodeIfPresent(String.self, forKey: .userId)
        totalConcepts = try c.decodeIfPresent(Int.self, forKey: .totalConcepts)
        totalNotes = try c.decodeIfPresent(Int.self, forKey: .totalNotes)
        totalReviews = try c.decodeIfPresent(Int.self, forKey: .totalReviews)
        streakDays = try c.decodeIfPresent(Int.self, forKey: .streakDays)
        accuracyRate = try c.decodeIfPresent(Double.self, forKey: .accuracyRate)
        dueToday = try c.decodeIfPresent(Int.self, forKey: .dueToday)
        completedToday = try c.decodeIfPresent(Int.self, forKey: .completedToday)
        dailyGoal = try c.decodeIfPresent(Int.self, forKey: .dailyGoal)
        overdue = try c.decodeIfPresent(Int.self, forKey: .overdue)
        dailyActivity = try c.decodeIfPresent([DailyActivity].self, forKey: .dailyActivity) ?? []
    }
}

struct DueCountResponse: Codable, Sendable {
    let dueToday: Int
    let overdue: Int
    let total: Int
    enum CodingKeys: String, CodingKey {
        case dueToday = "due_today"
        case overdue
        case total
    }
}

struct ReviewSubmitResult: Codable, Sendable {
    let status: String?
    let nextReview: String?
    let newIntervalDays: Int?
    let easinessFactor: Double?
    let streak: Int?
    enum CodingKeys: String, CodingKey {
        case status
        case nextReview = "next_review"
        case newIntervalDays = "new_interval_days"
        case easinessFactor = "easiness_factor"
        case streak
    }
}

struct PendingOfflineReview: Codable, Sendable, Identifiable, Hashable {
    var id: String { "\(itemId)-\(queuedAt.timeIntervalSince1970)" }
    let itemId: String
    let itemType: String
    let difficulty: ReviewDifficulty
    let queuedAt: Date
    /// Optional so reviews queued by older builds still decode.
    var conceptId: String? = nil
}

struct FeedLikeResponse: Codable, Sendable {
    let id: String?
    let isLiked: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case isLiked = "is_liked"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(String.self, forKey: .id)
        isLiked = try c.decodeIfPresent(Bool.self, forKey: .isLiked) ?? false
    }
}

struct FeedSaveResponse: Codable, Sendable {
    let id: String?
    let isSaved: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case isSaved = "is_saved"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(String.self, forKey: .id)
        isSaved = try c.decodeIfPresent(Bool.self, forKey: .isSaved) ?? false
    }
}

