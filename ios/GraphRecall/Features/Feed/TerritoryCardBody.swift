import SwiftUI

/// Map-the-territory: "Supervised learning — name its parts." The answer key is your own graph
/// (the concept's subtopics). Type or dictate what you remember; the backend matches each item
/// (acronyms, plurals, typos) and the card reveals what you named and what you missed.
struct TerritoryCardBody: View {
    let item: FeedItem
    /// Lets the host (feed or review session) show its grading controls once the answer is checked.
    var onReveal: () -> Void = {}

    @State private var answer = ""
    @State private var result: TerritoryResult?
    @State private var isChecking = false
    @State private var errorMessage: String?
    @State private var dictation = GRDictation()
    @FocusState private var focused: Bool

    private var parent: String { item.stringContent("parent") ?? item.conceptName ?? "This topic" }
    private var count: Int { (item.content["count"]?.value as? Int) ?? children.count }
    private var children: [String] {
        (item.content["children"]?.value as? [[String: Any]])?.compactMap { $0["name"] as? String } ?? []
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: "map.fill")
                    .foregroundStyle(GRColor.accentCyan)
                Text(parent)
                    .font(GRType.title)
                    .foregroundStyle(GRColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text("Name its \(count) parts from memory. Your graph is the answer key.")
                .font(GRType.body)
                .foregroundStyle(GRColor.textSecondary)

            if let result {
                resultView(result)
            } else {
                answerField
            }
        }
        .onDisappear { dictation.stop() }
    }

    // MARK: - Answer

    private var answerField: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                TextField("One per line or comma-separated", text: $answer, axis: .vertical)
                    .lineLimit(3...8)
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textPrimary)
                    .focused($focused)
                    .padding(12)
                    .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .accessibilityIdentifier("territory.answer")
                GRIconButton(
                    systemImage: dictation.isRecording ? "stop.fill" : "mic.fill",
                    style: dictation.isRecording ? .accent : .glass,
                    tint: dictation.isRecording ? GRColor.canvas : GRColor.accent,
                    size: 40,
                    accessibilityLabel: dictation.isRecording ? "Stop dictation" : "Say them"
                ) {
                    GRHaptics.tap()
                    if dictation.isRecording { dictation.stop() } else { Task { await dictation.start { answer = $0 } } }
                }
            }
            if let err = dictation.errorMessage ?? errorMessage {
                Text(err).font(GRType.caption).foregroundStyle(GRColor.warning)
            }
            HStack {
                Button("Show me") { Task { await check(reveal: true) } }
                    .grButton(.secondary, fullWidth: false, compact: true)
                Spacer()
                Button {
                    Task { await check(reveal: false) }
                } label: {
                    if isChecking { ProgressView().tint(GRColor.canvas) } else { Label("Check", systemImage: "checkmark") }
                }
                .grButton(.primary, fullWidth: false, compact: true)
                .disabled(answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isChecking)
                .accessibilityIdentifier("territory.check")
            }
        }
    }

    private func check(reveal: Bool) async {
        dictation.stop()
        focused = false
        isChecking = true
        defer { isChecking = false }
        let text = reveal ? "" : answer
        var r: TerritoryResult
        if let conceptId = item.conceptId,
           let server = try? await APIClient.shared.answerTerritory(conceptId: conceptId, answer: text) {
            r = server
        } else {
            // Offline or the server is unreachable: grade on device against the children the card shipped with.
            r = Self.gradeLocally(children: children, answer: text)
            errorMessage = nil
        }
        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) { result = r }
        onReveal()
        if !reveal { r.score >= 0.6 ? GRHaptics.success() : GRHaptics.warning() }
    }

    /// Simple on-device fallback: normalised equality or containment either way. The server's matcher
    /// (acronyms, typos) is better; this only keeps the card usable offline.
    static func gradeLocally(children: [String], answer: String) -> TerritoryResult {
        func norm(_ s: String) -> String {
            s.lowercased().components(separatedBy: CharacterSet.alphanumerics.inverted).filter { !$0.isEmpty }.joined(separator: " ")
        }
        let items = answer.components(separatedBy: CharacterSet(charactersIn: ",;\n")).map(norm).filter { !$0.isEmpty }
        var used = Set<Int>()
        var matched: [TerritoryMatch] = [], missed: [TerritoryMatch] = []
        for child in children {
            let c = norm(child)
            if let i = items.indices.first(where: { !used.contains($0) && (items[$0] == c || c.contains(items[$0]) || items[$0].contains(c)) }) {
                used.insert(i)
                matched.append(TerritoryMatch(id: nil, name: child, said: items[i]))
            } else {
                missed.append(TerritoryMatch(id: nil, name: child, said: nil))
            }
        }
        let score = children.isEmpty ? 0 : Double(matched.count) / Double(children.count)
        let grade = score >= 0.85 ? "easy" : score >= 0.6 ? "good" : score >= 0.3 ? "hard" : "again"
        let extras = items.indices.filter { !used.contains($0) }.map { items[$0] }
        return TerritoryResult(matched: matched, missed: missed, extras: extras, score: score,
                               suggestedDifficulty: grade, total: children.count)
    }

    // MARK: - Result

    private func resultView(_ r: TerritoryResult) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                GRProgressRing(progress: r.score, lineWidth: 5, tint: r.score >= 0.6 ? GRColor.success : GRColor.amber) {
                    Text("\(r.matched.count)/\(r.total)")
                        .font(GRType.caption.weight(.bold))
                        .foregroundStyle(GRColor.textPrimary)
                }
                .frame(width: 52, height: 52)
                VStack(alignment: .leading, spacing: 2) {
                    Text(headline(r)).font(GRType.headline).foregroundStyle(GRColor.textPrimary)
                    Text("Suggested grade: \(r.suggestedDifficulty.capitalized)")
                        .font(GRType.caption).foregroundStyle(GRColor.textSecondary)
                }
            }
            if !r.matched.isEmpty {
                chipSection("You named", r.matched.map(\.name), tone: .success, icon: "checkmark")
            }
            if !r.missed.isEmpty {
                chipSection("You missed", r.missed.map(\.name), tone: .amber, icon: "plus")
            }
            if !r.extras.isEmpty {
                chipSection("Not in your graph under \(parent)", r.extras, tone: .neutral, icon: nil)
            }
        }
        .transition(.opacity.combined(with: .move(edge: .bottom)))
    }

    private func headline(_ r: TerritoryResult) -> String {
        switch r.score {
        case 0.85...: return "You know this map"
        case 0.6..<0.85: return "Most of the territory"
        case 0.01..<0.6: return "Some gaps to fill"
        default: return "Here's the map"
        }
    }

    private func chipSection(_ title: String, _ names: [String], tone: GRTone, icon: String?) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased()).font(GRType.micro).foregroundStyle(GRColor.textTertiary)
            GRFlowLayout(spacing: 6) {
                ForEach(names, id: \.self) { n in
                    GRChip(title: n, systemImage: icon, style: .tinted(tone), compact: true)
                }
            }
        }
    }
}
