import SwiftUI

// LeetCode recall: log a problem in your own words; the backend turns it into pattern,
// pseudocode-with-hidden-lines and past-mistake cards that come back in the feed.

private let commonPatterns = [
    "Two Pointers", "Sliding Window", "Binary Search", "Hash Map", "Prefix Sum", "Monotonic Stack",
    "Heap", "BFS", "DFS", "Backtracking", "Dynamic Programming", "Greedy", "Union-Find",
    "Topological Sort", "Trie", "Intervals", "Linked List", "Bit Manipulation",
]

// MARK: - List

@MainActor
@Observable
final class LeetCodeListViewModel {
    var problems: [CodingProblemSummary] = []
    var weakSpots: [WeakSpot] = []
    var isLoading = false
    var errorMessage: String?

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let p = APIClient.shared.codingProblems()
            async let w = APIClient.shared.codingWeakSpots()
            problems = try await p
            weakSpots = (try? await w) ?? []
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "problems")
        }
    }
}

struct LeetCodeListView: View {
    @State private var model = LeetCodeListViewModel()
    @State private var showEditor = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                GRScreenHeader(title: "LeetCode", subtitle: "Recall the pattern, not the code")

                if !model.weakSpots.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        GRSectionHeader(title: "Where you slip")
                        GRFlowLayout(spacing: 8) {
                            ForEach(model.weakSpots.prefix(8)) { spot in
                                GRChip(title: "\(spot.label) · \(spot.pattern) ×\(spot.n)", style: .tinted(.coral), compact: true)
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                }

                Group {
                    if model.isLoading && model.problems.isEmpty {
                        ProgressView().tint(GRColor.accent).frame(maxWidth: .infinity, minHeight: 120)
                    } else if let err = model.errorMessage, model.problems.isEmpty {
                        Text(err).font(GRType.caption).foregroundStyle(GRColor.warning)
                    } else if model.problems.isEmpty {
                        GlassCard {
                            VStack(alignment: .leading, spacing: 10) {
                                Text("Log your first problem").font(GRType.headline).foregroundStyle(GRColor.textPrimary)
                                Text("Title, the pattern, the one insight and your pseudocode. Mistakes you log come back as cards.")
                                    .font(GRType.caption).foregroundStyle(GRColor.textSecondary)
                                Button { showEditor = true } label: { Label("Add problem", systemImage: "plus") }
                                    .grButton(.ghost, fullWidth: false, compact: true)
                            }
                        }
                    } else {
                        LazyVStack(spacing: 10) {
                            ForEach(model.problems) { p in
                                NavigationLink(value: p) { row(p) }
                                    .buttonStyle(.plain)
                            }
                        }
                    }
                }
                .padding(.horizontal, 20)
            }
            .padding(.bottom, 24)
        }
        .background(GRColor.canvas.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(for: CodingProblemSummary.self) { p in
            LeetCodeDetailView(problemId: p.id, title: p.title) { Task { await model.load() } }
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { showEditor = true } label: { Image(systemName: "plus") }
                    .accessibilityLabel("Add problem")
            }
        }
        .sheet(isPresented: $showEditor) {
            LeetCodeEditorSheet(existing: nil) { _ in Task { await model.load() } }
        }
        .task { await model.load() }
        .refreshable { await model.load() }
    }

    private func row(_ p: CodingProblemSummary) -> some View {
        let outcome = p.lastOutcome.flatMap(CodingOutcome.init(rawValue:))
        let difficulty = p.difficulty.flatMap(CodingDifficulty.init(rawValue:))
        return GRListRow(
            title: p.title,
            subtitle: [p.pattern, difficulty?.title].compactMap { $0 }.joined(separator: " · "),
            meta: outcome.map { "\($0.title)" } ?? (p.attempts == 0 ? "No attempts" : nil),
            metaColor: outcome?.tone.color ?? GRColor.textTertiary,
            systemImage: "chevron.left.forwardslash.chevron.right",
            tone: difficulty?.tone ?? .cyan
        )
    }
}

// MARK: - Editor

struct LeetCodeEditorSheet: View {
    let existing: CodingProblemDetail?
    var onSaved: ((CodingProblemSaved) -> Void)? = nil

    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var link = ""
    @State private var difficulty: CodingDifficulty?
    @State private var pattern = ""
    @State private var insight = ""
    @State private var pseudocode = ""
    @State private var complexity = ""
    @State private var isSaving = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Problem") {
                    TextField("Title, e.g. Longest Substring Without Repeating Characters", text: $title)
                        .accessibilityIdentifier("leetcode.title")
                    TextField("Link (optional)", text: $link)
                        .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Picker("Difficulty", selection: $difficulty) {
                        Text("Not set").tag(CodingDifficulty?.none)
                        ForEach(CodingDifficulty.allCases) { Text($0.title).tag(CodingDifficulty?.some($0)) }
                    }
                }
                Section {
                    TextField("Pattern", text: $pattern)
                        .accessibilityIdentifier("leetcode.pattern")
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            ForEach(commonPatterns, id: \.self) { p in
                                GRChip(title: p, style: pattern == p ? .selected : .plain, compact: true) { pattern = p }
                            }
                        }
                    }
                    TextField("The one insight that cracks it", text: $insight, axis: .vertical)
                        .lineLimit(2...4)
                    TextField("Complexity, e.g. O(n) time, O(k) space", text: $complexity)
                } header: { Text("How it's solved") } footer: {
                    Text("This becomes a “which pattern, and why?” card.")
                }
                Section {
                    TextEditor(text: $pseudocode)
                        .font(.system(.footnote, design: .monospaced))
                        .frame(minHeight: 160)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .accessibilityIdentifier("leetcode.pseudocode")
                } header: { Text("Pseudocode") } footer: {
                    Text("Three or more lines: the three most important ones are hidden on the card for you to fill in.")
                }
                if let errorMessage {
                    Section { Text(errorMessage).foregroundStyle(GRColor.warning) }
                }
            }
            .scrollContentBackground(.hidden)
            .background(GRColor.canvas.ignoresSafeArea())
            .navigationTitle(existing == nil ? "New problem" : "Edit problem")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await save() } } label: {
                        if isSaving { ProgressView() } else { Text("Save").bold() }
                    }
                    .disabled(title.trimmingCharacters(in: .whitespaces).count < 2 || isSaving)
                    .accessibilityIdentifier("leetcode.save")
                }
            }
        }
        .preferredColorScheme(.dark)
        .tint(GRColor.accent)
        .onAppear(perform: prefill)
    }

    private func prefill() {
        guard let p = existing else { return }
        title = p.title
        link = p.url ?? ""
        difficulty = p.difficulty.flatMap(CodingDifficulty.init(rawValue:))
        pattern = p.pattern ?? ""
        insight = p.keyInsight ?? ""
        pseudocode = p.pseudocode ?? ""
        complexity = p.complexity ?? ""
    }

    private func blankToNil(_ s: String) -> String? {
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        do {
            let saved = try await APIClient.shared.saveCodingProblem(CodingProblemBody(
                title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                url: blankToNil(link),
                difficulty: difficulty?.rawValue,
                pattern: blankToNil(pattern),
                keyInsight: blankToNil(insight),
                pseudocode: blankToNil(pseudocode),
                complexity: blankToNil(complexity)
            ))
            GRHaptics.success()
            onSaved?(saved)
            dismiss()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "problem")
        }
    }
}

// MARK: - Detail

struct LeetCodeDetailView: View {
    let problemId: String
    let title: String
    var onChange: (() -> Void)? = nil

    @State private var detail: CodingProblemDetail?
    @State private var errorMessage: String?
    @State private var showEditor = false
    @State private var showAttempt = false
    @State private var revealed: Set<String> = []
    @Environment(\.openURL) private var openURL

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                GRScreenHeader(title: detail?.title ?? title, subtitle: subtitle)

                if let detail {
                    HStack(spacing: 8) {
                        Button { showAttempt = true } label: { Label("Log attempt", systemImage: "plus.circle") }
                            .grButton(.primary, fullWidth: false, compact: true)
                            .accessibilityIdentifier("leetcode.logAttempt")
                        Button { showEditor = true } label: { Label("Edit", systemImage: "pencil") }
                            .grButton(.secondary, fullWidth: false, compact: true)
                        if let link = detail.url.flatMap(URL.init(string:)) {
                            Button { openURL(link) } label: { Label("Open", systemImage: "safari") }
                                .grButton(.ghost, fullWidth: false, compact: true)
                        }
                    }
                    .padding(.horizontal, 20)

                    cardsSection(detail.cards ?? [])
                        .padding(.horizontal, 20)

                    attemptsSection(detail.attempts ?? [])
                        .padding(.horizontal, 20)
                } else if let errorMessage {
                    Text(errorMessage).font(GRType.caption).foregroundStyle(GRColor.warning).padding(.horizontal, 20)
                } else {
                    ProgressView().tint(GRColor.accent).frame(maxWidth: .infinity, minHeight: 120)
                }
            }
            .padding(.bottom, 24)
        }
        .background(GRColor.canvas.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .sheet(isPresented: $showEditor) {
            LeetCodeEditorSheet(existing: detail) { _ in Task { await load(); onChange?() } }
        }
        .sheet(isPresented: $showAttempt) {
            LeetCodeAttemptSheet(problemId: problemId) { _ in Task { await load(); onChange?() } }
                .presentationDetents([.medium, .large])
        }
    }

    private var subtitle: String {
        guard let d = detail else { return "" }
        return [d.pattern, d.difficulty?.capitalized, d.complexity].compactMap { $0 }.joined(separator: " · ")
    }

    private func load() async {
        do {
            detail = try await APIClient.shared.codingProblem(id: problemId)
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "problem")
        }
    }

    private func cardsSection(_ cards: [RecallCardPreview]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Your cards (\(cards.count))")
            if cards.isEmpty {
                Text("Add a pattern, insight or pseudocode to get cards.")
                    .font(GRType.caption).foregroundStyle(GRColor.textSecondary)
            }
            ForEach(cards) { card in
                let open = revealed.contains(card.id)
                Button {
                    withAnimation(.easeOut(duration: 0.2)) {
                        if open { revealed.remove(card.id) } else { revealed.insert(card.id) }
                    }
                    GRHaptics.tap()
                } label: {
                    GlassCard(cornerRadius: 16) {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(card.front)
                                .font(card.front.contains("[___]") ? .system(.footnote, design: .monospaced) : GRType.body)
                                .foregroundStyle(GRColor.textPrimary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            if open {
                                Divider().overlay(GRColor.stroke)
                                Text(card.back)
                                    .font(card.back.contains("\n    ") ? .system(.footnote, design: .monospaced) : GRType.body)
                                    .foregroundStyle(GRColor.accent)
                            } else {
                                Text("Tap to reveal").font(GRType.micro).foregroundStyle(GRColor.textTertiary)
                            }
                        }
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func attemptsSection(_ attempts: [CodingAttempt]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Attempts")
            if attempts.isEmpty {
                Text("None yet.").font(GRType.caption).foregroundStyle(GRColor.textSecondary)
            }
            ForEach(attempts.reversed()) { a in
                let outcome = CodingOutcome(rawValue: a.outcome)
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        GRChip(title: outcome?.title ?? a.outcome, style: .tinted(outcome?.tone ?? .neutral), compact: true)
                        if let tag = a.mistakeTag.flatMap(MistakeTag.init(rawValue:)) {
                            GRChip(title: tag.title, style: .outline, compact: true)
                        }
                        Spacer()
                        if let m = a.minutes { Text("\(m) min").font(GRType.micro).foregroundStyle(GRColor.textTertiary) }
                        if let d = a.createdAt {
                            Text(d.formatted(date: .abbreviated, time: .omitted)).font(GRType.micro).foregroundStyle(GRColor.textTertiary)
                        }
                    }
                    if let m = a.mistake, !m.isEmpty {
                        Text(m).font(GRType.caption).foregroundStyle(GRColor.textSecondary)
                    }
                }
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(GRColor.fillSubtle))
            }
        }
    }
}

// MARK: - Attempt sheet

struct LeetCodeAttemptSheet: View {
    let problemId: String
    var onLogged: ((CodingAttemptLogged) -> Void)? = nil

    @Environment(\.dismiss) private var dismiss
    @State private var outcome: CodingOutcome = .solved
    @State private var mistake = ""
    @State private var tag: MistakeTag?
    @State private var minutes = ""
    @State private var dictation = GRDictation()
    @State private var isSaving = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("How did it go?") {
                    Picker("Outcome", selection: $outcome) {
                        ForEach(CodingOutcome.allCases) { Text($0.title).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    TextField("Minutes (optional)", text: $minutes).keyboardType(.numberPad)
                }
                Section {
                    HStack(alignment: .top) {
                        TextField("What tripped you up?", text: $mistake, axis: .vertical)
                            .lineLimit(2...5)
                            .accessibilityIdentifier("leetcode.mistake")
                        Button {
                            if dictation.isRecording { dictation.stop() } else { Task { await dictation.start { mistake = $0 } } }
                        } label: {
                            Image(systemName: dictation.isRecording ? "stop.circle.fill" : "mic.circle.fill").font(.title2)
                        }
                        .buttonStyle(.borderless)
                        .accessibilityLabel(dictation.isRecording ? "Stop dictation" : "Dictate the mistake")
                    }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            ForEach(MistakeTag.allCases) { t in
                                GRChip(title: t.title, style: tag == t ? .selected : .plain, compact: true) {
                                    tag = tag == t ? nil : t
                                }
                            }
                        }
                    }
                } header: { Text("Mistake") } footer: {
                    Text(outcome == .failed
                         ? "Logged mistakes become cards, and a failed attempt brings this problem back in your feed now."
                         : "Logged mistakes become “what's the trap?” cards.")
                }
                if let errorMessage { Section { Text(errorMessage).foregroundStyle(GRColor.warning) } }
            }
            .scrollContentBackground(.hidden)
            .background(GRColor.canvas.ignoresSafeArea())
            .navigationTitle("Log attempt")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cancel") { dictation.stop(); dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await save() } } label: { if isSaving { ProgressView() } else { Text("Save").bold() } }
                        .disabled(isSaving)
                        .accessibilityIdentifier("leetcode.saveAttempt")
                }
            }
        }
        .preferredColorScheme(.dark)
        .tint(GRColor.accent)
        .onDisappear { dictation.stop() }
    }

    private func save() async {
        dictation.stop()
        isSaving = true
        defer { isSaving = false }
        let text = mistake.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            let logged = try await APIClient.shared.logCodingAttempt(problemId: problemId, CodingAttemptBody(
                outcome: outcome.rawValue,
                mistake: text.isEmpty ? nil : text,
                mistakeTag: tag?.rawValue,
                minutes: Int(minutes.trimmingCharacters(in: .whitespaces))
            ))
            GRHaptics.success()
            onLogged?(logged)
            dismiss()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "attempt")
        }
    }
}
