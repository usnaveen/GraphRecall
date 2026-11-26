import SwiftUI

/// NAV-25 — Distinct SwiftUI layouts per `FeedItemType`, mirrored from web `FeedCardContent`.
struct FeedTypedCard: View {
    let item: FeedItem
    let revealed: Bool
    var selectedOptionId: String? = nil
    var fillAnswer: String = ""
    var showHint: Bool = false
    /// False when the feed already provides the card container around this content.
    var showsContainer: Bool = true
    /// Shown as a chip in the header, so the card needs no second header row.
    var isRevisit: Bool = false
    var onReveal: () -> Void = {}
    var onSelectOption: (String) -> Void = { _ in }
    var onFillAnswerChange: (String) -> Void = { _ in }
    var onToggleHint: () -> Void = {}

    @ViewBuilder
    var body: some View {
        if showsContainer {
            GlassCard { content }
        } else {
            content
        }
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: 12) {
            headerRow
            switch item.itemType {
            case .flashcard:
                flashcardBody
            case .mcq:
                mcqBody
            case .fillBlank:
                fillBlankBody
            case .showcase:
                showcaseBody
            case .codeChallenge:
                codeBody
            case .codeSandbox:
                CodeSandboxCardBody(
                    item: item,
                    onReveal: onReveal,
                    onComplete: { passed, total, elapsedMs in
                        let payload = item.sandboxPayload
                        let conceptName = item.conceptName ?? payload.title
                        Task {
                            _ = try? await APIClient.shared.submitSandboxResult(
                                challengeId: payload.challengeId,
                                conceptName: conceptName,
                                passed: passed,
                                total: total,
                                elapsedMs: elapsedMs
                            )
                        }
                    }
                )
                .id(item.id)
            case .diagram:
                diagramBody
            case .screenshot, .infographic:
                mediaBody
            case .territory:
                TerritoryCardBody(item: item, onReveal: onReveal)
                    .id(item.id)
            case .spotTheBug:
                SpotTheBugCardBody(item: item, onReveal: onReveal)
                    .id(item.id)
            case .tradeoffDuel:
                TradeoffDuelCardBody(item: item, onReveal: onReveal)
                    .id(item.id)
            case .diagramOcclusion:
                DiagramOcclusionCardBody(item: item, onReveal: onReveal)
                    .id(item.id)
            case .agentCurated:
                AgentCuratedCardBody(item: item, revealed: revealed, onReveal: onReveal)
            case .unknown:
                // Normally filtered out by FeedViewModel; generic plain-text fallback if one slips through.
                Text(verbatim: item.title)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                Text("This card type needs a newer version of GraphRecall.")
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textTertiary)
            }
        }
    }

    private var headerRow: some View {
        HStack(spacing: 8) {
            Text(item.itemType.displayLabel.uppercased())
                .font(GRType.caption)
                .foregroundStyle(typeColor)
            if isRevisit {
                Text("REVISIT")
                    .font(GRType.micro.weight(.bold))
                    .foregroundStyle(GRColor.accentCyan)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 2)
                    .overlay(Capsule().stroke(GRColor.accentCyan.opacity(0.6), lineWidth: 1))
            }
            if item.isDemo {
                Text("DEMO")
                    .font(GRType.micro.weight(.bold))
                    .foregroundStyle(GRColor.canvas)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(GRColor.warning, in: Capsule())
            }
            Spacer()
            if let domain = item.domain, !domain.isEmpty {
                Text(domain == "concept_dump" ? "DUMP" : domain)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textTertiary)
            }
        }
    }

    private var typeColor: Color {
        switch item.itemType {
        case .fillBlank, .codeChallenge, .codeSandbox, .territory, .agentCurated, .spotTheBug:
            return GRColor.accentCyan
        case .screenshot, .infographic:
            return Color(red: 1, green: 0.42, blue: 0.42)
        case .diagram, .tradeoffDuel, .diagramOcclusion:
            return GRColor.purple
        default:
            return GRColor.accent
        }
    }

    // MARK: - Flashcard / Term Card

    @ViewBuilder
    private var flashcardBody: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(item.prompt)
                .font(.title3.weight(.semibold))
                .foregroundStyle(GRColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            if revealed, let answer = item.answer {
                Divider().overlay(GRColor.stroke)
                Text(answer)
                    .font(.body)
                    .foregroundStyle(GRColor.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                // After the answer only: the picture is centred on the concept's name, which is
                // often exactly what the card asks for.
                revealedFigure
            } else if !revealed {
                revealButton(title: "Show answer")
            }
            sourcesBlock
        }
    }

    // MARK: - MCQ / Quiz

    @ViewBuilder
    private var mcqBody: some View {
        let options = item.mcqOptions
        VStack(alignment: .leading, spacing: 12) {
            Text(item.prompt)
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            ForEach(options) { opt in
                Button {
                    onSelectOption(opt.id)
                } label: {
                    HStack(alignment: .top, spacing: 10) {
                        Circle()
                            .strokeBorder(optionBorder(opt), lineWidth: 1.5)
                            .background(Circle().fill(optionFill(opt)))
                            .frame(width: 22, height: 22)
                        Text(opt.text)
                            .font(.subheadline)
                            .foregroundStyle(GRColor.textPrimary)
                            .multilineTextAlignment(.leading)
                        Spacer(minLength: 0)
                    }
                    .padding(.vertical, 4)
                }
                .buttonStyle(.glass)
                .buttonBorderShape(.roundedRectangle(radius: 14))
                .buttonSizing(.flexible)
                .tint(optionBorder(opt))
                .allowsHitTesting(!revealed)
                .accessibilityIdentifier("review.option")
            }

            if revealed {
                if let explanation = item.stringContent("explanation") {
                    Text(explanation)
                        .font(.subheadline)
                        .foregroundStyle(GRColor.textSecondary)
                        .padding(.top, 4)
                }
                revealedFigure
            } else if selectedOptionId != nil {
                revealButton(title: "Check answer")
            }
            sourcesBlock
        }
    }

    private func optionBorder(_ opt: FeedMCQOption) -> Color {
        if revealed {
            if opt.isCorrect { return Color.green.opacity(0.7) }
            if opt.id == selectedOptionId { return Color.red.opacity(0.7) }
        }
        return opt.id == selectedOptionId ? GRColor.accent : GRColor.stroke
    }

    private func optionFill(_ opt: FeedMCQOption) -> Color {
        if revealed && opt.isCorrect { return Color.green.opacity(0.35) }
        if revealed && opt.id == selectedOptionId { return Color.red.opacity(0.35) }
        if opt.id == selectedOptionId { return GRColor.accent.opacity(0.35) }
        return Color.clear
    }

    // MARK: - Fill blank

    @ViewBuilder
    private var fillBlankBody: some View {
        let sentence = item.stringContent("sentence") ?? item.prompt
        let parts = sentence.components(separatedBy: "__________")
        let blank = revealed
            ? (item.firstAnswerFromList() ?? "…")
            : (fillAnswer.isEmpty ? "…" : fillAnswer)

        VStack(alignment: .leading, spacing: 12) {
            (
                Text(parts.first ?? "")
                + Text(blank).foregroundColor(GRColor.accentCyan).underline()
                + Text(parts.count > 1 ? parts[1] : "")
            )
            .font(GRType.headline)
            .foregroundStyle(GRColor.textPrimary)
            .fixedSize(horizontal: false, vertical: true)

            if !revealed {
                TextField("Type your answer…", text: Binding(
                    get: { fillAnswer },
                    set: { onFillAnswerChange($0) }
                ))
                .textInputAutocapitalization(.never)
                .padding(12)
                .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .foregroundStyle(GRColor.textPrimary)

                if showHint, let hint = item.stringContent("hint") {
                    Text("💡 \(hint)")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.accentCyan)
                }

                HStack(spacing: 8) {
                    Button(action: onToggleHint) {
                        Text("Show hint")
                            .font(GRType.caption.weight(.semibold))
                    }
                    .grButton(.secondary)
                    Button(action: onReveal) {
                        Text("Show answer")
                            .font(GRType.caption.weight(.semibold))
                    }
                    .grButton(.primary)
                    .accessibilityIdentifier("review.reveal")
                }
            } else if let ans = item.firstAnswerFromList() {
                Text("Answer: \(ans)")
                    .font(.subheadline)
                    .foregroundStyle(Color.green.opacity(0.9))
                revealedFigure
            }
        }
    }

    // MARK: - Showcase

    private var showcaseDefinition: String {
        item.stringContent("definition") ?? item.stringContent("description") ?? item.prompt
    }

    /// Key points that add something: a point that only repeats the definition is dropped.
    private var showcaseKeyPoints: [String] {
        let norm: (String) -> String = { text in
            text.lowercased().filter { $0.isLetter || $0.isNumber }
        }
        let definition = norm(showcaseDefinition)
        var seen = Set<String>()
        let points = item.keyPoints.filter { point in
            let key = norm(point)
            guard !key.isEmpty, key != definition, !definition.contains(key) else { return false }
            return seen.insert(key).inserted
        }
        return points
    }

    @ViewBuilder
    private var showcaseBody: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                if let emoji = item.stringContent("emoji_icon") ?? item.stringContent("emojiIcon") {
                    Text(emoji).font(.title2)
                }
                Text(item.conceptName ?? item.stringContent("title") ?? item.title)
                    .font(.title2.weight(.bold))
                    .foregroundStyle(GRColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let tagline = item.stringContent("tagline"),
               tagline.caseInsensitiveCompare(item.domain ?? "") != .orderedSame,
               tagline.caseInsensitiveCompare(item.conceptName ?? "") != .orderedSame {
                Text("“\(tagline)”")
                    .font(GRType.caption)
                    .italic()
                    .foregroundStyle(GRColor.accent)
            }
            ConceptVisual(item: item)
                .padding(.vertical, 4)

            Text(showcaseDefinition)
                .font(.body)
                .foregroundStyle(GRColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            ForEach(Array(showcaseKeyPoints.enumerated()), id: \.offset) { _, point in
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "arrow.right")
                        .font(.caption)
                        .foregroundStyle(GRColor.accentCyan)
                        .padding(.top, 2)
                    Text(point)
                        .font(.subheadline)
                        .foregroundStyle(GRColor.textSecondary)
                }
            }

            if let example = item.stringContent("real_world_example") ?? item.stringContent("realWorldExample") {
                VStack(alignment: .leading, spacing: 4) {
                    Text("REAL-WORLD EXAMPLE")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    Text(example)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
        }
    }

    // MARK: - Code

    @ViewBuilder
    private var codeBody: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(item.stringContent("language")?.uppercased() ?? "CODE")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(GRColor.fillSubtle, in: Capsule())
                Spacer()
            }
            Text(item.stringContent("instruction") ?? item.prompt)
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            if let initial = item.stringContent("initial_code") ?? item.stringContent("initialCode") {
                Text(initial)
                    .font(.system(.footnote, design: .monospaced))
                    .foregroundStyle(GRColor.accentCyan)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.black.opacity(0.35), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }

            if revealed {
                if let solution = item.stringContent("solution_code") ?? item.stringContent("solutionCode") {
                    Text(solution)
                        .font(.system(.footnote, design: .monospaced))
                        .foregroundStyle(GRColor.accent)
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(GRColor.accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                if let explanation = item.stringContent("explanation") {
                    Text(explanation)
                        .font(.subheadline)
                        .foregroundStyle(GRColor.textSecondary)
                }
            } else {
                revealButton(title: "Reveal solution")
            }
        }
    }

    // MARK: - Diagram

    @ViewBuilder
    private var diagramBody: some View {
        let code = item.stringContent("mermaid_code")
            ?? item.stringContent("mermaidCode")
            ?? ""
        let nodes = Self.parseMermaidNodes(code)
        let caption = item.stringContent("caption") ?? item.conceptName ?? "Concept Map"

        VStack(alignment: .leading, spacing: 12) {
            Text(caption)
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)

            VStack(spacing: 10) {
                Text(nodes.center)
                    .font(GRType.caption.weight(.semibold))
                    .foregroundStyle(GRColor.accent)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(GRColor.accent.opacity(0.15), in: RoundedRectangle(cornerRadius: 10, style: .continuous))

                FlowWrap(items: nodes.children)
            }
            .frame(maxWidth: .infinity)
            .padding(14)
            .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
    }

    // MARK: - Screenshot / Infographic

    @ViewBuilder
    private var mediaBody: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let title = item.stringContent("title") ?? item.conceptName {
                Text(title)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
            }
            if let desc = item.stringContent("description") {
                Text(desc)
                    .font(.subheadline)
                    .foregroundStyle(GRColor.textSecondary)
            }

            ZStack {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(GRColor.fillSubtle)
                    .frame(minHeight: 160)
                if let url = item.imageURL {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let img):
                            img.resizable().scaledToFit().frame(maxHeight: 240)
                        default:
                            placeholderMedia
                        }
                    }
                } else {
                    placeholderMedia
                }
            }

            if !item.linkedConcepts.isEmpty {
                Text("Linked concepts")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                FlowWrap(items: item.linkedConcepts, tint: Color(red: 1, green: 0.42, blue: 0.42))
            }
        }
    }

    private var placeholderMedia: some View {
        VStack(spacing: 8) {
            Image(systemName: "photo")
                .font(.largeTitle)
                .foregroundStyle(GRColor.textTertiary)
            Text(item.isDemo ? "Demo upload placeholder" : "Image unavailable")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textTertiary)
        }
        .padding(24)
    }

    // MARK: - Shared

    /// Quiz-style cards show the concept's picture only once answered: it names the concept.
    @ViewBuilder
    private var revealedFigure: some View {
        if item.hasConceptVisual {
            ConceptVisual(item: item)
                .padding(.top, 4)
        }
    }

    private func revealButton(title: String) -> some View {
        Button(action: onReveal) {
            Text(title)
                .font(GRType.caption.weight(.bold))
        }
        .grButton(.primary)
        .accessibilityIdentifier("review.reveal")
        .padding(.top, 4)
    }

    @ViewBuilder
    private var sourcesBlock: some View {
        if revealed, let sources = item.content["sources"]?.value as? [[String: String]], !sources.isEmpty {
            Text("Sources")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textTertiary)
            ForEach(Array(sources.prefix(3).enumerated()), id: \.offset) { _, src in
                if let urlString = src["url"], let url = URL(string: urlString), !urlString.isEmpty {
                    Link(src["title"].flatMap { $0.isEmpty ? nil : $0 } ?? urlString, destination: url)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.accentCyan)
                }
            }
        }
    }

    private static func parseMermaidNodes(_ code: String) -> (center: String, children: [String]) {
        let lines = code.split(whereSeparator: \.isNewline).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        var nodes: [String] = []
        var center = "Concept"
        let pattern = try? NSRegularExpression(pattern: #"[(\[{]+([^)\]}]+)[)\]}]+"#)
        for line in lines {
            guard let pattern else { continue }
            let range = NSRange(line.startIndex..<line.endIndex, in: line)
            pattern.enumerateMatches(in: line, options: [], range: range) { match, _, _ in
                guard let match, let r = Range(match.range(at: 1), in: line) else { return }
                let text = String(line[r]).trimmingCharacters(in: .whitespaces)
                if !text.isEmpty { nodes.append(text) }
            }
        }
        if let first = nodes.first { center = first }
        let children = Array(Set(nodes.filter { $0 != center })).prefix(8).map { $0 }
        return (center, Array(children))
    }
}

/// Lightweight wrapping chip row for diagram / linked concepts.
private struct FlowWrap: View {
    let items: [String]
    var tint: Color = GRColor.accent

    var body: some View {
        FlexibleChipStack(items: items, tint: tint)
    }
}

private struct FlexibleChipStack: View {
    let items: [String]
    var tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(chunked(items, size: 3), id: \.self) { row in
                HStack(spacing: 6) {
                    ForEach(row, id: \.self) { item in
                        Text(item)
                            .font(GRType.micro)
                            .foregroundStyle(tint)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(tint.opacity(0.12), in: Capsule())
                    }
                }
            }
        }
    }

    private func chunked(_ values: [String], size: Int) -> [[String]] {
        stride(from: 0, to: values.count, by: size).map {
            Array(values[$0..<min($0 + size, values.count)])
        }
    }
}

/// NAV-34 — Shared like / save / share chrome under every review card.
struct FeedCardActionBar: View {
    let item: FeedItem
    let isLiked: Bool
    let isSaved: Bool
    var onLike: () -> Void = {}
    var onSave: () -> Void = {}

    var body: some View {
        HStack(spacing: 10) {
            actionButton(
                systemName: isLiked ? "heart.fill" : "heart",
                active: isLiked,
                accessibilityLabel: isLiked ? "Unlike" : "Like",
                action: onLike
            )
            actionButton(
                systemName: isSaved ? "bookmark.fill" : "bookmark",
                active: isSaved,
                accessibilityLabel: isSaved ? "Unsave" : "Save",
                action: onSave
            )
            ShareLink(item: item.sharePlainText) {
                Image(systemName: "square.and.arrow.up")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(GRColor.textSecondary)
                    .frame(width: 24, height: 24)
            }
            .buttonStyle(.glass)
            .buttonBorderShape(.circle)
            .accessibilityLabel("Share card")
            Spacer(minLength: 0)
        }
        .padding(.top, 2)
    }

    private func actionButton(
        systemName: String,
        active: Bool,
        accessibilityLabel: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.body.weight(.semibold))
                .foregroundStyle(active ? GRColor.accent : GRColor.textSecondary)
                .frame(width: 24, height: 24)
        }
        .buttonStyle(.glass)
        .buttonBorderShape(.circle)
        .accessibilityLabel(accessibilityLabel)
    }
}

