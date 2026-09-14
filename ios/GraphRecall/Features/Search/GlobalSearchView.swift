import SwiftUI

/// One search across concepts (API), cached due cards, notes and past chats.
struct GlobalSearchView: View {
    enum Scope: String, CaseIterable, Identifiable {
        case all = "All", concepts = "Concepts", cards = "Cards", notes = "Notes", chats = "Chats"
        var id: String { rawValue }
    }

    @Environment(\.dismiss) private var dismiss
    @Environment(AppRouter.self) private var router
    @State private var query = ""
    @State private var scope: Scope = .all
    @State private var concepts: [GraphSearchResult] = []
    @State private var allCards: [FeedItem] = []
    @State private var allNotes: [LibraryNote] = []
    @State private var allChats: [ChatConversationSummary] = []
    @State private var isSearching = false
    @State private var revealedCardIds: Set<String> = []
    @State private var readingNote: LibraryNote?
    @FocusState private var focused: Bool

    private var trimmed: String { query.trimmingCharacters(in: .whitespacesAndNewlines) }

    private var cards: [FeedItem] {
        guard !trimmed.isEmpty else { return [] }
        return allCards.filter {
            $0.prompt.localizedCaseInsensitiveContains(trimmed)
                || ($0.answer?.localizedCaseInsensitiveContains(trimmed) ?? false)
                || ($0.conceptName?.localizedCaseInsensitiveContains(trimmed) ?? false)
        }
    }

    private var notes: [LibraryNote] {
        guard !trimmed.isEmpty else { return [] }
        return allNotes.filter {
            $0.displayTitle.localizedCaseInsensitiveContains(trimmed)
                || ($0.contentText?.localizedCaseInsensitiveContains(trimmed) ?? false)
        }
    }

    private var chats: [ChatConversationSummary] {
        guard !trimmed.isEmpty else { return [] }
        return allChats.filter {
            $0.displayTitle.localizedCaseInsensitiveContains(trimmed)
                || ($0.lastMessage?.localizedCaseInsensitiveContains(trimmed) ?? false)
        }
    }

    private func count(_ scope: Scope) -> Int {
        switch scope {
        case .all: return concepts.count + cards.count + notes.count + chats.count
        case .concepts: return concepts.count
        case .cards: return cards.count
        case .notes: return notes.count
        case .chats: return chats.count
        }
    }

    private func shows(_ section: Scope) -> Bool { scope == .all || scope == section }

    var body: some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass").foregroundStyle(GRColor.textTertiary)
                    TextField("Search everything", text: $query)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .foregroundStyle(GRColor.textPrimary)
                        .focused($focused)
                        .submitLabel(.search)
                    if isSearching { ProgressView().controlSize(.small).tint(GRColor.accent) }
                    if !query.isEmpty {
                        Button { query = "" } label: {
                            Image(systemName: "xmark.circle.fill").foregroundStyle(GRColor.textTertiary)
                        }
                        .accessibilityLabel("Clear search")
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
                .grGlassEffect(.interactive, in: RoundedRectangle(cornerRadius: 16, style: .continuous))

                Button("Cancel") { dismiss() }
                    .font(GRType.caption.weight(.bold))
                    .foregroundStyle(GRColor.accent)
            }
            .padding(.horizontal, 20)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(Scope.allCases) { item in
                        GRChip(
                            title: trimmed.isEmpty ? item.rawValue : "\(item.rawValue) · \(count(item))",
                            style: scope == item ? .selected : .plain,
                            compact: true
                        ) {
                            scope = item
                        }
                    }
                }
                .padding(.horizontal, 20)
            }

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    if trimmed.isEmpty {
                        GRBanner(
                            systemImage: "sparkles",
                            title: "Search everything",
                            subtitle: "Concepts, due cards, notes and past chats in one place.",
                            tone: .accent
                        )
                    } else {
                        askRow
                        if shows(.concepts), !concepts.isEmpty { conceptsSection }
                        if shows(.cards), !cards.isEmpty { cardsSection }
                        if shows(.notes), !notes.isEmpty { notesSection }
                        if shows(.chats), !chats.isEmpty { chatsSection }
                        if count(scope) == 0 && !isSearching {
                            GRBanner(systemImage: "magnifyingglass", title: "No matches", subtitle: "Try another word, or ask the Assistant.", tone: .neutral)
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 32)
            }
        }
        .padding(.top, 20)
        .background(GRColor.canvas.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .task {
            focused = true
            await loadCorpus()
        }
        .task(id: trimmed) { await searchConcepts() }
        .sheet(item: $readingNote) { note in
            NoteReaderView(note: note)
        }
    }

    // MARK: - Sections

    private var askRow: some View {
        Button {
            router.ask(trimmed)
            dismiss()
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "sparkles")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(GRColor.accent)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Ask Assistant about “\(trimmed)”")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.accent)
                        .lineLimit(1)
                    Text("Grounded answer from your graph and notes")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(GRColor.accent)
            }
            .padding(14)
            .background(GRColor.accentSoft, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(GRColor.accentLine, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    private var conceptsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Concepts")
            ForEach(concepts.prefix(scope == .concepts ? 20 : 4)) { concept in
                Button {
                    router.focusInGraph(concept.id)
                    dismiss()
                } label: {
                    GRListRow(
                        title: concept.name,
                        subtitle: concept.domain,
                        meta: "Open",
                        metaColor: GRColor.accent,
                        systemImage: "point.3.connected.trianglepath.dotted",
                        tone: .accent
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var cardsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Cards")
            ForEach(cards.prefix(scope == .cards ? 30 : 4)) { card in
                Button {
                    if revealedCardIds.contains(card.id) {
                        revealedCardIds.remove(card.id)
                    } else {
                        revealedCardIds.insert(card.id)
                    }
                } label: {
                    VStack(alignment: .leading, spacing: 8) {
                        GRListRow(
                            title: card.prompt,
                            subtitle: [card.itemType.displayLabel, card.conceptName].compactMap { $0 }.joined(separator: " · "),
                            meta: revealedCardIds.contains(card.id) ? "Hide" : "Answer",
                            metaColor: GRColor.accent,
                            systemImage: card.itemType.systemImage,
                            tone: card.itemType.tone,
                            showsChevron: false
                        )
                        if revealedCardIds.contains(card.id), let answer = card.answer {
                            Text(answer)
                                .font(GRType.body)
                                .foregroundStyle(GRColor.textSecondary)
                                .padding(.horizontal, 14)
                                .transition(.opacity)
                        }
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var notesSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Notes & books")
            ForEach(notes.prefix(scope == .notes ? 30 : 4)) { note in
                Button {
                    if (note.resourceType ?? "").lowercased() == "book" {
                        dismiss()
                        NotificationCenter.default.post(name: .grNavigateLibrary, object: nil)
                    } else {
                        readingNote = note
                    }
                } label: {
                    GRListRow(
                        title: note.displayTitle,
                        subtitle: [note.resourceType?.capitalized, ProfileDateFormat.short(note.createdAt)].compactMap { $0 }.joined(separator: " · "),
                        systemImage: (note.resourceType ?? "").lowercased() == "book" ? "books.vertical.fill" : "doc.text.fill",
                        tone: .coral
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var chatsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Chats")
            ForEach(chats.prefix(scope == .chats ? 30 : 4)) { chat in
                Button {
                    router.openConversation(chat.id)
                    dismiss()
                } label: {
                    GRListRow(
                        title: chat.displayTitle,
                        subtitle: chat.displaySubtitle,
                        systemImage: "bubble.left.and.bubble.right.fill",
                        tone: .amber
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: - Data

    private func loadCorpus() async {
        async let cached = OfflineReviewStore.shared.cachedFeed()
        async let notesResult = try? APIClient.shared.fetchNotes(limit: 100)
        let hasAuth = await APIClient.shared.hasAuthToken
        allCards = await cached?.items ?? []
        allNotes = await notesResult?.notes ?? []
        if hasAuth {
            allChats = (try? await APIClient.shared.getChatHistory(limit: 50).conversations) ?? []
        }
    }

    private func searchConcepts() async {
        let q = trimmed
        guard !q.isEmpty else {
            concepts = []
            return
        }
        try? await Task.sleep(nanoseconds: 250_000_000)
        guard !Task.isCancelled else { return }
        isSearching = true
        defer { isSearching = false }
        do {
            concepts = try await APIClient.shared.searchConcepts(q, limit: 20)
        } catch {
            concepts = GraphViewModel.stubGraph().nodes
                .filter { $0.name.localizedCaseInsensitiveContains(q) }
                .map { GraphSearchResult(id: $0.id, name: $0.name, domain: $0.domain, color: $0.color) }
        }
    }
}

struct NoteReaderView: View {
    let note: LibraryNote
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                ScrollView {
                    Text(note.contentText ?? "This note has no text content.")
                        .font(GRType.body)
                        .foregroundStyle(GRColor.textPrimary)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(20)
                }
            }
            .navigationTitle(note.displayTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .foregroundStyle(GRColor.accent)
                }
            }
        }
        .preferredColorScheme(.dark)
    }
}
