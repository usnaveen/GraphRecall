import SwiftUI

// MARK: - 1. Spot the Bug Card Body

/// Interactive 1-based line-grading code debugging card (`spot_the_bug`).
/// Tapping any code line highlights it, triggers haptics, reveals `explanation` + `fixed_line`,
/// invokes `onReveal()`, and records quiz evidence via `APIClient.shared.gradeSpotTheBug`.
struct SpotTheBugCardBody: View {
    let item: FeedItem
    var onReveal: () -> Void

    @State private var selectedLine: Int?
    @State private var isRevealed = false
    @State private var hasSubmittedGrade = false

    init(item: FeedItem, onReveal: @escaping () -> Void = {}) {
        self.item = item
        self.onReveal = onReveal
    }

    private var payload: SpotTheBugPayload { item.spotTheBugPayload }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            headerRow

            Text("Tap the buggy line in this snippet.")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)

            codeContainer

            if isRevealed {
                explanationPanel
            } else {
                HStack {
                    Spacer(minLength: 0)
                    Button {
                        revealWithoutGuess()
                    } label: {
                        Label("Show bug", systemImage: "eye")
                            .font(GRType.caption.weight(.semibold))
                    }
                    .buttonStyle(.glass)
                    .buttonBorderShape(.capsule)
                    .controlSize(.small)
                    .foregroundStyle(GRColor.textSecondary)
                    .accessibilityIdentifier("spotTheBug.reveal")
                }
            }
        }
        .onChange(of: item.id) { _, _ in
            selectedLine = nil
            isRevealed = false
            hasSubmittedGrade = false
        }
    }

    private var headerRow: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: "ladybug.fill")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(GRColor.accentCyan)

            Text(payload.title)
                .font(GRType.title)
                .foregroundStyle(GRColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: 4)

            GRChip(title: payload.language.uppercased(), style: .tinted(.cyan), compact: true)
        }
    }

    private var codeContainer: some View {
        VStack(alignment: .leading, spacing: 2) {
            ForEach(Array(payload.lines.enumerated()), id: \.offset) { idx, lineText in
                let lineNumber = idx + 1
                codeLineRow(lineNumber: lineNumber, text: lineText)
            }
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(GRColor.canvas)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(GRColor.strokeStrong, lineWidth: 1)
        )
    }

    private func codeLineRow(lineNumber: Int, text: String) -> some View {
        let isBugLine = lineNumber == payload.buggyLineIndex
        let isPicked = selectedLine == lineNumber
        let hitBug = isPicked && isBugLine

        let rowFill: Color = {
            guard isRevealed else { return Color.clear }
            if hitBug { return GRColor.accentSoft }
            if isPicked && !isBugLine { return GRColor.coral.opacity(0.16) }
            if isBugLine { return GRColor.amber.opacity(0.14) }
            return Color.clear
        }()

        let rowStroke: Color = {
            guard isRevealed else { return Color.clear }
            if hitBug { return GRColor.accent }
            if isPicked && !isBugLine { return GRColor.coral }
            if isBugLine { return GRColor.amber.opacity(0.75) }
            return Color.clear
        }()

        let numberColor: Color = {
            guard isRevealed else { return GRColor.textTertiary }
            if hitBug { return GRColor.accent }
            if isPicked { return GRColor.coral }
            if isBugLine { return GRColor.amber }
            return GRColor.textTertiary
        }()

        let codeColor: Color = {
            guard isRevealed else { return GRColor.accentCyan }
            if hitBug { return GRColor.accent }
            if isPicked && !isBugLine { return GRColor.coral }
            if isBugLine { return GRColor.amber }
            return GRColor.textPrimary.opacity(0.88)
        }()

        return Button {
            selectLine(lineNumber)
        } label: {
            HStack(alignment: .top, spacing: 10) {
                Text("\(lineNumber)")
                    .font(.system(.caption2, design: .monospaced).weight(.semibold))
                    .foregroundStyle(numberColor)
                    .frame(width: 22, alignment: .trailing)
                    .padding(.top, 2)

                Text(text.isEmpty ? " " : text)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(codeColor)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if isRevealed {
                    if hitBug {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(GRColor.accent)
                    } else if isPicked {
                        Image(systemName: "xmark.circle.fill")
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(GRColor.coral)
                    } else if isBugLine {
                        Image(systemName: "ladybug.fill")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(GRColor.amber)
                    }
                }
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 7)
            .background(rowFill, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .stroke(rowStroke, lineWidth: rowStroke == .clear ? 0 : 1)
            )
            .contentShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
        }
        .buttonStyle(.plain)
        .allowsHitTesting(!isRevealed)
        .accessibilityIdentifier("spotTheBug.line.\(lineNumber)")
    }

    private var explanationPanel: some View {
        let hit = selectedLine == payload.buggyLineIndex
        let verdictTone: GRTone = hit ? .accent : (selectedLine == nil ? .amber : .coral)
        let verdictTitle: String = {
            if hit {
                return "Bug spotted on line \(payload.buggyLineIndex)"
            }
            if let picked = selectedLine {
                return "Line \(picked) is safe · Bug is on line \(payload.buggyLineIndex)"
            }
            return "Bug is on line \(payload.buggyLineIndex)"
        }()

        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: hit ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(verdictTone.color)
                Text(verdictTitle)
                    .font(GRType.headline)
                    .foregroundStyle(verdictTone.color)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Text(payload.explanation)
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            if !payload.fixedLine.isEmpty {
                VStack(alignment: .leading, spacing: 5) {
                    Text("FIXED LINE")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.accent)

                    Text(payload.fixedLine)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(GRColor.accent)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .fill(GRColor.canvas)
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .stroke(GRColor.accentLine, lineWidth: 1)
                        )
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .grGlassEffect(.regular, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .transition(.opacity.combined(with: .move(edge: .bottom)))
    }

    private func selectLine(_ lineNumber: Int) {
        guard !isRevealed else { return }
        let isHit = lineNumber == payload.buggyLineIndex
        if isHit {
            GRHaptics.success()
        } else {
            GRHaptics.warning()
        }
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            selectedLine = lineNumber
            isRevealed = true
        }
        onReveal()

        guard !hasSubmittedGrade else { return }
        hasSubmittedGrade = true
        let cardId = payload.cardId
        Task {
            _ = try? await APIClient.shared.gradeSpotTheBug(cardId: cardId, selectedLine: lineNumber)
        }
    }

    private func revealWithoutGuess() {
        guard !isRevealed else { return }
        GRHaptics.tap()
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            selectedLine = nil
            isRevealed = true
        }
        onReveal()
    }
}

// MARK: - 2. Tradeoff Duel Card Body

/// System-design architecture comparison card (`tradeoff_duel`).
/// Renders `scenario` + two tappable Liquid Glass option cards (`Option A` vs `Option B`),
/// then reveals `recommended`, `winning_rationale`, and `when_other_wins`.
struct TradeoffDuelCardBody: View {
    let item: FeedItem
    var onReveal: () -> Void

    @State private var selectedChoice: String?
    @State private var isRevealed = false

    init(item: FeedItem, onReveal: @escaping () -> Void = {}) {
        self.item = item
        self.onReveal = onReveal
    }

    private var payload: TradeoffDuelPayload { item.tradeoffDuelPayload }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            headerRow

            Text(payload.scenario)
                .font(GRType.body)
                .foregroundStyle(GRColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            duelOptionsStack

            if isRevealed {
                rationalePanel
            }
        }
        .onChange(of: item.id) { _, _ in
            selectedChoice = nil
            isRevealed = false
        }
    }

    private var headerRow: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: "arrow.left.arrow.right.circle.fill")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(GRColor.purple)

            Text(payload.title)
                .font(GRType.title)
                .foregroundStyle(GRColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var duelOptionsStack: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: 10) {
                optionCard(key: "a", badge: "OPTION A", text: payload.optionA)
                optionCard(key: "b", badge: "OPTION B", text: payload.optionB)
            }
            VStack(spacing: 10) {
                optionCard(key: "a", badge: "OPTION A", text: payload.optionA)
                optionCard(key: "b", badge: "OPTION B", text: payload.optionB)
            }
        }
    }

    @ViewBuilder
    private func optionCard(key: String, badge: String, text: String) -> some View {
        let isSelected = selectedChoice == key
        let isWinner = payload.recommended == key
        let isDepends = payload.recommended == "depends"

        let accentTint: Color = {
            guard isRevealed else { return GRColor.accentCyan }
            if isDepends { return isSelected ? GRColor.accentCyan : GRColor.strokeStrong }
            if isWinner { return GRColor.accent }
            if isSelected { return GRColor.amber }
            return GRColor.stroke
        }()

        let statusIcon: String? = {
            guard isRevealed else { return nil }
            if isDepends { return "scale.3d" }
            if isWinner { return "checkmark.seal.fill" }
            if isSelected { return "arrow.triangle.branch" }
            return nil
        }()

        let labelContent = VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Text(badge)
                    .font(GRType.micro.weight(.bold))
                    .foregroundStyle(isRevealed && isWinner ? GRColor.canvas : accentTint)
                Spacer(minLength: 0)
                if let statusIcon {
                    Image(systemName: statusIcon)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(isRevealed && isWinner ? GRColor.canvas : accentTint)
                }
            }

            Text(text)
                .font(GRType.caption.weight(.semibold))
                .foregroundStyle(isRevealed && isWinner ? GRColor.canvas : GRColor.textPrimary)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)

        let button = Button {
            pickOption(key)
        } label: {
            labelContent
        }
        .buttonBorderShape(.roundedRectangle(radius: 16))
        .buttonSizing(.flexible)
        .allowsHitTesting(!isRevealed)
        .accessibilityIdentifier("tradeoffDuel.option.\(key)")

        if isRevealed && isWinner {
            button
                .buttonStyle(.glassProminent)
                .tint(GRColor.accent)
        } else if isRevealed && (isSelected || isDepends) {
            button
                .buttonStyle(.glass)
                .tint(accentTint)
        } else {
            button
                .buttonStyle(.glass)
        }
    }

    private var rationalePanel: some View {
        let verdictLabel: String = {
            switch payload.recommended {
            case "a": return "Recommended: Option A"
            case "b": return "Recommended: Option B"
            default: return "It Depends — Workload Tradeoff"
            }
        }()

        let verdictColor: Color = payload.recommended == "depends" ? GRColor.accentCyan : GRColor.accent

        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: payload.recommended == "depends" ? "scale.3d" : "trophy.fill")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(verdictColor)
                Text(verdictLabel)
                    .font(GRType.headline)
                    .foregroundStyle(verdictColor)
            }

            if !payload.winningRationale.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text(payload.recommended == "depends" ? "CORE TRADEOFF" : "WHY IT WINS")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    Text(payload.winningRationale)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            if !payload.whenOtherWins.isEmpty {
                Divider().overlay(GRColor.stroke)
                VStack(alignment: .leading, spacing: 4) {
                    Text(payload.recommended == "depends" ? "DECISION BOUNDARY" : "WHEN THE OTHER WINS")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.accentCyan)
                    Text(payload.whenOtherWins)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .grGlassEffect(.regular, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .transition(.opacity.combined(with: .move(edge: .bottom)))
    }

    private func pickOption(_ choice: String) {
        guard !isRevealed else { return }
        if payload.recommended == "depends" || payload.recommended == choice {
            GRHaptics.success()
        } else {
            GRHaptics.warning()
        }
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            selectedChoice = choice
            isRevealed = true
        }
        onReveal()
    }
}

// MARK: - 3. Diagram Occlusion Card Body

/// Interactive diagram check card (`diagram_occlusion`) supporting:
/// - Mermaid occluded diagrams with `[SLOT_1]`.. interactive slot chips and tappable option pills.
/// - Validated `http(s)` figure cards with `AsyncImage`, caption prompt, and `"Reveal takeaway"`.
struct DiagramOcclusionCardBody: View {
    let item: FeedItem
    var onReveal: () -> Void

    @State private var activeSlot: String?
    @State private var filledSlots: [String: String] = [:]
    @State private var isRevealed = false

    init(item: FeedItem, onReveal: @escaping () -> Void = {}) {
        self.item = item
        self.onReveal = onReveal
    }

    private var payload: DiagramOcclusionPayload { item.diagramOcclusionPayload }
    private var slots: [String] { payload.orderedSlots }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            headerRow

            Text(payload.prompt)
                .font(GRType.body)
                .foregroundStyle(GRColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            if payload.isFigure {
                figureContent
            } else {
                mermaidContent
            }
        }
        .onAppear {
            if activeSlot == nil {
                activeSlot = slots.first
            }
        }
        .onChange(of: item.id) { _, _ in
            filledSlots = [:]
            isRevealed = false
            activeSlot = item.diagramOcclusionPayload.orderedSlots.first
        }
    }

    private var headerRow: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: payload.isFigure ? "photo" : "point.3.connected.trianglepath.dotted")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(GRColor.purple)

            Text(payload.title)
                .font(GRType.title)
                .foregroundStyle(GRColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: 4)

            GRChip(
                title: payload.isFigure ? "FIGURE" : "DIAGRAM",
                style: .tinted(.purple),
                compact: true
            )
        }
    }

    // MARK: - Mermaid Occlusion Mode

    @ViewBuilder
    private var mermaidContent: some View {
        diagramCodePreview

        if !slots.isEmpty {
            slotChipsSection
        }

        if !isRevealed {
            if !payload.options.isEmpty && !slots.isEmpty {
                optionPillsSection
            }
            mermaidControlsRow
        } else {
            answerKeyPanel
        }
    }

    private var renderedMermaidPreview: String {
        if isRevealed, let original = payload.originalMermaid, !original.isEmpty {
            return original
        }
        guard var preview = payload.occludedMermaid, !preview.isEmpty else {
            return "flowchart LR\n  A[\"[SLOT_1]\"]"
        }
        for slot in slots {
            if isRevealed, let truth = payload.answerKey[slot] {
                preview = preview.replacingOccurrences(of: "[\(slot)]", with: "[\(slot): \(truth)]")
            } else if let chosen = filledSlots[slot] {
                preview = preview.replacingOccurrences(of: "[\(slot)]", with: "[\(slot): \(chosen)]")
            }
        }
        return preview
    }

    private var diagramCodePreview: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(isRevealed ? "COMPLETE DIAGRAM" : "OCCLUDED DIAGRAM")
                    .font(GRType.micro)
                    .foregroundStyle(isRevealed ? GRColor.accent : GRColor.textTertiary)
                Spacer()
                if !slots.isEmpty && !isRevealed {
                    Text("\(filledSlots.count)/\(slots.count) filled")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.accentCyan)
                }
            }

            ScrollView(.horizontal, showsIndicators: false) {
                Text(renderedMermaidPreview)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(isRevealed ? GRColor.accent : GRColor.accentCyan)
                    .multilineTextAlignment(.leading)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(GRColor.canvas)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(isRevealed ? GRColor.accentLine : GRColor.strokeStrong, lineWidth: 1)
            )
        }
    }

    private var slotChipsSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("SLOTS")
                .font(GRType.micro)
                .foregroundStyle(GRColor.textTertiary)

            GRFlowLayout(spacing: 8, lineSpacing: 8) {
                ForEach(slots, id: \.self) { slot in
                    slotChip(for: slot)
                }
            }
        }
    }

    private func slotChip(for slot: String) -> some View {
        let currentSelection = filledSlots[slot]
        let isFocused = (activeSlot ?? slots.first) == slot
        let expected = payload.answerKey[slot]
        let isCorrect = isRevealed && currentSelection != nil && currentSelection == expected

        let title: String = {
            if let currentSelection {
                return "[\(slot)] \(currentSelection)"
            }
            return "[\(slot)] ?"
        }()

        let chipStyle: GRChip.Style = {
            if isRevealed {
                if currentSelection == nil { return .tinted(.amber) }
                return isCorrect ? .tinted(.accent) : .tinted(.coral)
            }
            if isFocused { return .selected }
            if currentSelection != nil { return .tinted(.cyan) }
            return .outline
        }()

        let icon: String? = {
            guard isRevealed else { return isFocused ? "target" : nil }
            if currentSelection == nil { return "eye" }
            return isCorrect ? "checkmark" : "xmark"
        }()

        return GRChip(
            title: title,
            systemImage: icon,
            style: chipStyle,
            compact: true,
            action: isRevealed ? nil : {
                GRHaptics.tap()
                activeSlot = slot
            }
        )
    }

    private var optionPillsSection: some View {
        let targetSlot = activeSlot ?? slots.first ?? "SLOT_1"
        return VStack(alignment: .leading, spacing: 6) {
            Text("CHOOSE COMPONENT FOR [\(targetSlot)]")
                .font(GRType.micro)
                .foregroundStyle(GRColor.accentCyan)

            GRFlowLayout(spacing: 8, lineSpacing: 8) {
                ForEach(payload.options, id: \.self) { option in
                    let isAssignedToActive = filledSlots[targetSlot] == option
                    GRChip(
                        title: option,
                        systemImage: isAssignedToActive ? "checkmark" : nil,
                        style: isAssignedToActive ? .selected : .plain,
                        compact: false
                    ) {
                        assignOption(option, to: targetSlot)
                    }
                }
            }
        }
    }

    private var mermaidControlsRow: some View {
        let allFilled = !slots.isEmpty && slots.allSatisfy { filledSlots[$0] != nil }
        return HStack(spacing: 10) {
            Button {
                revealMermaid(checkScore: false)
            } label: {
                Text("Show answer key")
                    .font(GRType.caption.weight(.semibold))
            }
            .grButton(.secondary, fullWidth: false, compact: true)
            .accessibilityIdentifier("diagramOcclusion.showAnswerKey")

            Spacer(minLength: 0)

            if !slots.isEmpty && !payload.options.isEmpty {
                Button {
                    revealMermaid(checkScore: true)
                } label: {
                    Label("Check diagram", systemImage: "checkmark")
                        .font(GRType.caption.weight(.bold))
                }
                .grButton(.primary, fullWidth: false, compact: true)
                .disabled(!allFilled)
                .accessibilityIdentifier("diagramOcclusion.check")
            }
        }
    }

    private var answerKeyPanel: some View {
        let keys = slots.isEmpty ? DiagramOcclusionPayload.sortSlotKeys(Array(payload.answerKey.keys)) : slots
        return VStack(alignment: .leading, spacing: 8) {
            Text("ANSWER KEY")
                .font(GRType.micro)
                .foregroundStyle(GRColor.accent)

            ForEach(keys, id: \.self) { slot in
                if let truth = payload.answerKey[slot] {
                    let picked = filledSlots[slot]
                    let matched = picked == truth
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: matched ? "checkmark.circle.fill" : "arrow.turn.down.right")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(matched ? GRColor.accent : GRColor.accentCyan)
                            .padding(.top, 2)

                        VStack(alignment: .leading, spacing: 2) {
                            Text("[\(slot)] → \(truth)")
                                .font(GRType.caption.weight(.semibold))
                                .foregroundStyle(GRColor.textPrimary)
                                .fixedSize(horizontal: false, vertical: true)
                            if let picked, !matched {
                                Text("You picked: \(picked)")
                                    .font(GRType.micro)
                                    .foregroundStyle(GRColor.coral)
                            }
                        }
                    }
                }
            }

            sourceLinkRow
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .grGlassEffect(.regular, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .transition(.opacity.combined(with: .move(edge: .bottom)))
    }

    private func assignOption(_ option: String, to slot: String) {
        GRHaptics.tap()
        withAnimation(.easeInOut(duration: 0.18)) {
            filledSlots[slot] = option
            if let nextEmpty = slots.first(where: { filledSlots[$0] == nil }) {
                activeSlot = nextEmpty
            }
        }
    }

    private func revealMermaid(checkScore: Bool) {
        guard !isRevealed else { return }
        if checkScore && !slots.isEmpty {
            let allCorrect = slots.allSatisfy { slot in
                guard let expected = payload.answerKey[slot] else { return true }
                return filledSlots[slot] == expected
            }
            if allCorrect {
                GRHaptics.success()
            } else {
                GRHaptics.warning()
            }
        } else {
            GRHaptics.tap()
        }
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            isRevealed = true
        }
        onReveal()
    }

    // MARK: - HTTP(S) Figure Mode

    @ViewBuilder
    private var figureContent: some View {
        figureImageContainer

        if isRevealed {
            let takeaway = payload.answerKey["takeaway"]
                ?? payload.caption
                ?? payload.sourceTitle
            VStack(alignment: .leading, spacing: 8) {
                Text("KEY TAKEAWAY")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.accent)

                Text(takeaway.isEmpty ? "Review how the components in this figure interact." : takeaway)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                sourceLinkRow
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .grGlassEffect(.regular, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .transition(.opacity.combined(with: .move(edge: .bottom)))
        } else {
            Button {
                GRHaptics.tap()
                withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
                    isRevealed = true
                }
                onReveal()
            } label: {
                Text("Reveal takeaway")
                    .font(GRType.caption.weight(.bold))
            }
            .grButton(.primary, fullWidth: true, compact: true)
            .accessibilityIdentifier("diagramOcclusion.revealTakeaway")
        }
    }

    private var figureImageContainer: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(GRColor.canvas)
                .frame(minHeight: 170)

            if let url = payload.imageURL {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFit()
                            .frame(maxWidth: .infinity, maxHeight: 260)
                            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                            .padding(6)
                    case .empty:
                        ProgressView()
                            .tint(GRColor.accentCyan)
                            .padding(28)
                    case .failure:
                        figureFallback
                    @unknown default:
                        figureFallback
                    }
                }
            } else {
                figureFallback
            }
        }
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(GRColor.strokeStrong, lineWidth: 1)
        )
    }

    private var figureFallback: some View {
        VStack(spacing: 8) {
            Image(systemName: "photo")
                .font(.title2)
                .foregroundStyle(GRColor.textTertiary)
            Text(payload.caption ?? "Diagram figure unavailable offline")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
                .multilineTextAlignment(.center)
        }
        .padding(20)
    }

    @ViewBuilder
    private var sourceLinkRow: some View {
        if let sourceURL = payload.sourceURL {
            Link(destination: sourceURL) {
                HStack(spacing: 5) {
                    Image(systemName: "arrow.up.right.square")
                        .font(.system(size: 12, weight: .semibold))
                    Text(payload.sourceTitle.isEmpty ? "Open source" : payload.sourceTitle)
                        .font(GRType.caption.weight(.semibold))
                        .lineLimit(1)
                }
                .foregroundStyle(GRColor.accentCyan)
            }
            .padding(.top, 2)
        }
    }
}
