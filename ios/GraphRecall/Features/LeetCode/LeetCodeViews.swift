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
    // Number-first: the rest fills in from LeetCode.
    @State private var numberText = ""
    @State private var found: LeetCodeLookup?
    @State private var isLookingUp = false
    @State private var lookupMessage: String?
    @State private var lookupTask: Task<Void, Never>?
    @State private var outcome: CodingOutcome?
    @State private var code = ""
    // Filled by the lookup for new problems; typed for old ones or when the lookup can't help.
    @State private var title = ""
    @State private var link = ""
    @State private var difficulty: CodingDifficulty?
    @State private var tags: [String] = []
    @State private var pattern = ""
    @State private var insight = ""
    @State private var pseudocode = ""
    @State private var complexity = ""
    @State private var showsMore = false
    @State private var isSaving = false
    @State private var errorMessage: String?
    @FocusState private var numberFocused: Bool

    private var isNew: Bool { existing == nil }
    private var number: Int? { Int(numberText.trimmingCharacters(in: .whitespaces)) }
    private var canSave: Bool { title.trimmingCharacters(in: .whitespaces).count >= 2 && !isSaving && !isLookingUp }

    var body: some View {
        NavigationStack {
            Form {
                if isNew {
                    numberSection
                    if found != nil || lookupMessage != nil { outcomeSection }
                } else {
                    manualProblemSection
                }
                if found != nil || !isNew || lookupMessage != nil {
                    patternSection
                    notesSection
                    moreSection
                }
                if let errorMessage {
                    Section { Text(errorMessage).foregroundStyle(GRColor.warning) }
                }
            }
            .scrollContentBackground(.hidden)
            .background(GRColor.canvas.ignoresSafeArea())
            .navigationTitle(isNew ? "Log a problem" : "Edit problem")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await save() } } label: {
                        if isSaving { ProgressView() } else { Text("Save").bold() }
                    }
                    .disabled(!canSave)
                    .accessibilityIdentifier("leetcode.save")
                }
            }
        }
        .preferredColorScheme(.dark)
        .tint(GRColor.accent)
        .onAppear {
            prefill()
            if isNew { numberFocused = true }
        }
        .onDisappear { lookupTask?.cancel() }
    }

    // MARK: Sections

    private var numberSection: some View {
        Section {
            HStack(spacing: 10) {
                Text("#")
                    .font(.system(.title2, design: .monospaced).weight(.semibold))
                    .foregroundStyle(GRColor.textTertiary)
                TextField("Problem number", text: $numberText)
                    .font(.system(.title2, design: .monospaced).weight(.semibold))
                    .keyboardType(.numberPad)
                    .focused($numberFocused)
                    .accessibilityIdentifier("leetcode.number")
                    .onChange(of: numberText) { _, _ in scheduleLookup() }
                if isLookingUp { ProgressView() }
            }
            if let found {
                VStack(alignment: .leading, spacing: 6) {
                    Text(found.title)
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    HStack(spacing: 6) {
                        if let d = CodingDifficulty(rawValue: found.difficulty) {
                            GRChip(title: d.title, style: .tinted(d.tone), compact: true)
                        }
                        if found.paidOnly {
                            GRChip(title: "Premium", systemImage: "lock.fill", style: .outline, compact: true)
                        }
                        Link(destination: URL(string: found.url) ?? URL(string: "https://leetcode.com")!) {
                            Label("Open", systemImage: "arrow.up.right.square")
                                .font(GRType.caption)
                        }
                    }
                    if !found.tags.isEmpty {
                        Text(found.tags.joined(separator: " · "))
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                    }
                }
                .padding(.vertical, 2)
                .accessibilityIdentifier("leetcode.found")
            } else if let lookupMessage {
                Text(lookupMessage)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.warning)
                TextField("Title instead", text: $title)
                    .accessibilityIdentifier("leetcode.title")
            }
        } header: {
            Text("LeetCode problem")
        } footer: {
            if found == nil && lookupMessage == nil {
                Text("Just the number. Title, link, difficulty and topics come from LeetCode.")
            }
        }
    }

    private var outcomeSection: some View {
        Section("How did it go?") {
            HStack(spacing: 8) {
                ForEach(CodingOutcome.allCases) { o in
                    GRChip(title: o.title, style: outcome == o ? .selected : .plain, compact: true) {
                        outcome = (outcome == o) ? nil : o
                        GRHaptics.tap()
                    }
                }
            }
            .accessibilityIdentifier("leetcode.outcome")
        }
    }

    private var manualProblemSection: some View {
        Section("Problem") {
            if let n = existing?.number {
                LabeledContent("Number", value: "#\(n)")
            }
            TextField("Title, e.g. Longest Substring Without Repeating Characters", text: $title)
                .accessibilityIdentifier("leetcode.title")
            TextField("Link (optional)", text: $link)
                .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
            Picker("Difficulty", selection: $difficulty) {
                Text("Not set").tag(CodingDifficulty?.none)
                ForEach(CodingDifficulty.allCases) { Text($0.title).tag(CodingDifficulty?.some($0)) }
            }
        }
    }

    private var patternSection: some View {
        Section {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(commonPatterns, id: \.self) { p in
                        GRChip(title: p, style: pattern == p ? .selected : .plain, compact: true) { pattern = p }
                    }
                }
            }
            TextField("Pattern", text: $pattern)
                .accessibilityIdentifier("leetcode.pattern")
        } header: { Text("Pattern") } footer: {
            if found?.pattern != nil && pattern == found?.pattern {
                Text("Suggested from LeetCode's topics. Change it if you solved it another way.")
            }
        }
    }

    private var notesSection: some View {
        Section {
            TextField("The one insight that cracks it", text: $insight, axis: .vertical)
                .lineLimit(2...4)
            TextEditor(text: $code)
                .font(.system(.footnote, design: .monospaced))
                .frame(minHeight: 120)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .accessibilityIdentifier("leetcode.code")
                .overlay(alignment: .topLeading) {
                    if code.isEmpty {
                        Text("Paste your solution (optional)")
                            .font(.system(.footnote, design: .monospaced))
                            .foregroundStyle(GRColor.textTertiary)
                            .padding(.top, 8).padding(.leading, 5)
                            .allowsHitTesting(false)
                    }
                }
        } header: { Text("Your notes") } footer: {
            Text("The insight becomes a “which pattern, and why?” card.")
        }
    }

    private var moreSection: some View {
        Section {
            DisclosureGroup("For recall cards", isExpanded: $showsMore) {
                TextField("Complexity, e.g. O(n) time, O(k) space", text: $complexity)
                TextEditor(text: $pseudocode)
                    .font(.system(.footnote, design: .monospaced))
                    .frame(minHeight: 140)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .accessibilityIdentifier("leetcode.pseudocode")
                Text("Three or more lines of pseudocode: the three most important ones are hidden on a card for you to fill in.")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
            }
        }
    }

    // MARK: Lookup

    /// Looks the number up a moment after typing stops; a newer keystroke cancels the older lookup.
    private func scheduleLookup() {
        lookupTask?.cancel()
        found = nil
        lookupMessage = nil
        guard let n = number, n > 0 else {
            isLookingUp = false
            return
        }
        isLookingUp = true
        lookupTask = Task {
            try? await Task.sleep(for: .milliseconds(450))
            guard !Task.isCancelled else { return }
            do {
                let result = try await APIClient.shared.lookupLeetCode(number: n)
                guard !Task.isCancelled, number == n else { return }
                apply(result)
                GRHaptics.tap()
            } catch {
                guard !Task.isCancelled, number == n else { return }
                if case APIError.http(404, _) = error {
                    lookupMessage = "No LeetCode problem #\(n). Check the number, or type the title."
                } else {
                    lookupMessage = "Couldn't reach LeetCode just now. Type the title and save anyway."
                }
            }
            if number == n { isLookingUp = false }
        }
    }

    private func apply(_ r: LeetCodeLookup) {
        found = r
        title = r.title
        link = r.url
        difficulty = CodingDifficulty(rawValue: r.difficulty)
        tags = r.tags
        if pattern.isEmpty, let suggested = r.pattern { pattern = suggested }
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
        code = p.solution ?? ""
        showsMore = !(p.pseudocode ?? "").isEmpty
    }

    private func blankToNil(_ s: String) -> String? {
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }

    // MARK: Save

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
                complexity: blankToNil(complexity),
                number: found?.number ?? existing?.number,
                tags: tags.isEmpty ? nil : tags,
                solution: blankToNil(code)
            ))
            if let outcome {
                // How it went is an attempt, so the problem is scheduled like any other.
                _ = try? await APIClient.shared.logCodingAttempt(
                    problemId: saved.id,
                    CodingAttemptBody(outcome: outcome.rawValue, mistake: nil, mistakeTag: nil, minutes: nil)
                )
            }
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
