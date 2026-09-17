import SwiftUI
import UIKit

struct ChatView: View {
    @State private var model = ChatViewModel()
    @State private var dictation = GRDictation()
    @State private var openSource: ChatSourceRef?
    /// Whether the conversation is scrolled to (or near) the latest message.
    @State private var isNearBottom = true
    @FocusState private var inputFocused: Bool
    @Environment(AppRouter.self) private var router

    private static let bottomAnchor = "chat.bottom"
    private static let citationScheme = "grsource"

    var body: some View {
        @Bindable var bindable = model

        ZStack(alignment: .top) {
            GRColor.canvas.ignoresSafeArea()
            GRBackdropGlow(tint: GRColor.accentCyan, offset: CGSize(width: -150, height: -240))

            VStack(spacing: 0) {
                // While typing, the large title gives its room to the conversation.
                if inputFocused {
                    compactHeader
                        .transition(.opacity)
                } else {
                    header
                        .transition(.opacity)
                }
                scopeRow
                    .padding(.horizontal, 20)
                    .padding(.bottom, 6)
                messagesScroll
                if showsSuggestions {
                    suggestionsRow
                }
                composer(input: $bindable.input)
            }
            // The dock hides with the keyboard, so the composer can sit directly on the keys.
            .animation(.easeOut(duration: 0.22), value: inputFocused)

            if let banner = model.bannerMessage {
                GRToast(message: banner)
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .zIndex(2)
            }
        }
        .animation(.easeOut(duration: 0.22), value: model.bannerMessage)
        .task {
            await model.onAppear()
            consumeRouter()
        }
        .onChange(of: router.pendingAssistantPrompt) { _, _ in consumeRouter() }
        .onChange(of: router.pendingConversationId) { _, _ in consumeRouter() }
        .onDisappear { dictation.stop() }
        .sheet(isPresented: $bindable.showHistory) {
            ConversationHistorySheet(model: model)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $bindable.showNotePicker) {
            NoteScopePicker(initial: model.scopedNotes) { model.scopedNotes = $0 }
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $openSource) { source in
            SourceDetailSheet(source: source)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }

    private var showsSuggestions: Bool {
        !model.suggestions.isEmpty
            && model.messages.count <= 2
            && !model.isStreaming
            && model.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func consumeRouter() {
        if let id = router.pendingConversationId {
            router.pendingConversationId = nil
            Task { await model.selectConversation(id) }
        }
        if let prompt = router.pendingAssistantPrompt {
            router.pendingAssistantPrompt = nil
            if let topic = router.assistantFocusTopic {
                model.focusTopic = topic
                router.assistantFocusTopic = nil
            }
            model.input = prompt
            guard !model.isStreaming else { return }
            Task { await model.send() }
        }
    }

    // MARK: - Header

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            GRScreenHeader(title: "Assistant", subtitle: headerSubtitle)
            HStack(spacing: 8) {
                headerButtons(size: 44)
            }
            .padding(.trailing, 20)
            .padding(.top, 14)
        }
    }

    private var compactHeader: some View {
        HStack(spacing: 8) {
            Text("Assistant")
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
            if model.isStreaming {
                ProgressView()
                    .controlSize(.mini)
                    .tint(GRColor.accent)
            }
            Spacer()
            headerButtons(size: 34)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 8)
    }

    @ViewBuilder
    private func headerButtons(size: CGFloat) -> some View {
        GRIconButton(systemImage: "plus", size: size, accessibilityLabel: "New chat") {
            model.startNewChat()
        }
        .disabled(model.isStreaming)
        GRIconButton(systemImage: "clock.arrow.circlepath", tint: GRColor.textPrimary, size: size, accessibilityLabel: "Chat history") {
            inputFocused = false
            model.openHistory()
        }
        .disabled(model.isStreaming)
    }

    private var headerSubtitle: String {
        if model.usingStub { return "Offline demo · answers are local" }
        if let cid = model.conversationId, !cid.isEmpty { return "Thread active · grounded in your graph" }
        return "Grounded in your graph and notes"
    }

    private var scopeRow: some View {
        HStack(spacing: 6) {
            Text("Scope")
                .font(GRType.micro)
                .foregroundStyle(GRColor.textTertiary)
            if let topic = model.focusTopic {
                GRChip(title: topic, systemImage: "scope", style: .selected, compact: true)
                clearScopeButton("Clear concept scope") { model.focusTopic = nil }
            }
            if !model.scopedNotes.isEmpty {
                GRChip(title: notesScopeTitle, systemImage: "doc.text.fill", style: .selected, compact: true) {
                    model.showNotePicker = true
                }
                clearScopeButton("Clear notes scope") { model.scopedNotes = [] }
            } else {
                if model.focusTopic == nil {
                    GRChip(title: "Whole graph", systemImage: "point.3.connected.trianglepath.dotted", style: .selected, compact: true)
                }
                GRChip(title: "Notes only…", systemImage: "doc.text", style: .outline, compact: true) {
                    model.showNotePicker = true
                }
            }
            Spacer(minLength: 0)
        }
    }

    private var notesScopeTitle: String {
        if model.scopedNotes.count == 1, let title = model.scopedNotes[0].title, !title.isEmpty {
            return title
        }
        return "\(model.scopedNotes.count) notes"
    }

    private func clearScopeButton(_ label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(GRColor.textTertiary)
        }
        .accessibilityLabel(label)
    }

    // MARK: - Messages

    private var messagesScroll: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if let error = model.errorMessage {
                        GRBanner(systemImage: "exclamationmark.triangle.fill", title: "Chat issue", subtitle: error, tone: .warning)
                    }
                    ForEach(model.messages) { message in
                        messageBubble(message)
                            .id(message.id)
                    }
                    Color.clear
                        .frame(height: 1)
                        .id(Self.bottomAnchor)
                }
                .padding(.horizontal, 20)
                .padding(.top, 14)
                .padding(.bottom, 8)
            }
            .scrollDismissesKeyboard(.interactively)
            .onScrollGeometryChange(for: Bool.self) { geometry in
                geometry.contentOffset.y + geometry.containerSize.height >= geometry.contentSize.height - 120
            } action: { _, nearBottom in
                isNearBottom = nearBottom
            }
            // Tapping the conversation is a natural way out of typing.
            .simultaneousGesture(TapGesture().onEnded { inputFocused = false })
            .mask(topFade)
            .overlay(alignment: .bottomTrailing) {
                if !isNearBottom {
                    Button {
                        withAnimation(.easeOut(duration: 0.25)) {
                            proxy.scrollTo(Self.bottomAnchor, anchor: .bottom)
                        }
                    } label: {
                        Image(systemName: "arrow.down")
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(GRColor.textPrimary)
                            .frame(width: 38, height: 38)
                            .grGlassEffect(.interactive, in: Circle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Jump to latest message")
                    .padding(.trailing, 20)
                    .padding(.bottom, 10)
                    .transition(.scale.combined(with: .opacity))
                }
            }
            .animation(.easeOut(duration: 0.2), value: isNearBottom)
            .onChange(of: model.messages.count) { _, _ in
                // A new question or answer always brings the latest message into view.
                withAnimation(.easeOut(duration: 0.25)) {
                    proxy.scrollTo(Self.bottomAnchor, anchor: .bottom)
                }
            }
            .onChange(of: model.messages.last?.content) { _, _ in
                // Follow a streaming answer only if the reader hasn't scrolled up; no animation per token.
                guard isNearBottom else { return }
                proxy.scrollTo(Self.bottomAnchor, anchor: .bottom)
            }
            .onChange(of: model.messages.first?.id) { _, _ in
                // A conversation opened from history starts at its latest message.
                Task { @MainActor in
                    proxy.scrollTo(Self.bottomAnchor, anchor: .bottom)
                }
            }
            .onChange(of: router.isKeyboardVisible) { wasVisible, visible in
                guard visible, !wasVisible, isNearBottom else { return }
                Task { @MainActor in
                    try? await Task.sleep(for: .milliseconds(280))
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo(Self.bottomAnchor, anchor: .bottom)
                    }
                }
            }
        }
    }

    /// Messages fade out under the scope row instead of being cut off by a hard edge.
    private var topFade: some View {
        VStack(spacing: 0) {
            LinearGradient(colors: [.clear, .black], startPoint: .top, endPoint: .bottom)
                .frame(height: 18)
            Rectangle().fill(.black)
        }
    }

    @ViewBuilder
    private func messageBubble(_ message: ChatMessageUI) -> some View {
        if message.role == .user {
            HStack {
                Spacer(minLength: 48)
                Text(message.content)
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textPrimary)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 11)
                    .background(GRColor.accentSoft, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(GRColor.accentLine, lineWidth: 1))
                    .contextMenu {
                        Button {
                            UIPasteboard.general.string = message.content
                            GRHaptics.tap()
                        } label: {
                            Label("Copy", systemImage: "doc.on.doc")
                        }
                        Button {
                            model.input = message.content
                            inputFocused = true
                        } label: {
                            Label("Edit and resend", systemImage: "pencil")
                        }
                        .disabled(model.isStreaming)
                    }
            }
        } else {
            assistantBubble(message)
        }
    }

    private func assistantBubble(_ message: ChatMessageUI) -> some View {
        let sourceGroups = Self.sourceGroups(message.sources)

        return VStack(alignment: .leading, spacing: 10) {
            if message.isStreaming {
                HStack(spacing: 8) {
                    TypingDots()
                    Text(message.status ?? "Thinking…")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.accent)
                }
            } else if !sourceGroups.isEmpty || !message.relatedConcepts.isEmpty {
                Label(
                    "Grounded in \(message.relatedConcepts.count) concept\(message.relatedConcepts.count == 1 ? "" : "s") · \(sourceGroups.count) source\(sourceGroups.count == 1 ? "" : "s")",
                    systemImage: "sparkles"
                )
                .font(GRType.micro)
                .foregroundStyle(GRColor.textTertiary)
            }

            if !message.content.isEmpty {
                Text(Self.markdown(message.content, linkCitations: !message.sources.isEmpty))
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textPrimary)
                    .tint(GRColor.accentCyan)
                    .textSelection(.enabled)
                    .environment(\.openURL, OpenURLAction { url in
                        guard url.scheme == Self.citationScheme else { return .systemAction }
                        // "[n]" cites the n-th source the backend returned.
                        if let index = Int(url.host() ?? ""), message.sources.indices.contains(index - 1) {
                            openSource = Self.mergedSource(for: message.sources[index - 1], in: message.sources)
                        }
                        return .handled
                    })
            }

            if !message.relatedConcepts.isEmpty {
                GRFlowLayout(spacing: 6, lineSpacing: 6) {
                    ForEach(message.relatedConcepts, id: \.self) { concept in
                        GRChip(title: concept, style: .tinted(.accent), compact: true) {
                            router.focusInGraph(concept)
                        }
                    }
                }
            }

            if !sourceGroups.isEmpty {
                VStack(spacing: 6) {
                    ForEach(sourceGroups.prefix(4)) { group in
                        Button {
                            openSource = group.source
                        } label: {
                            HStack(spacing: 8) {
                                Image(systemName: "doc.text.fill")
                                    .font(.system(size: 12))
                                    .foregroundStyle(GRColor.accentCyan)
                                Text(group.source.title)
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.textSecondary)
                                    .lineLimit(1)
                                Spacer()
                                if group.excerptCount > 1 {
                                    Text("\(group.excerptCount) excerpts")
                                        .font(GRType.micro)
                                        .foregroundStyle(GRColor.textTertiary)
                                }
                                Image(systemName: "chevron.right")
                                    .font(.system(size: 10, weight: .semibold))
                                    .foregroundStyle(GRColor.textTertiary)
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 8)
                            .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }

            if showsActions(message) {
                Divider().overlay(GRColor.stroke)
                actionRow(message)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .padding(.trailing, 20)
    }

    private func showsActions(_ message: ChatMessageUI) -> Bool {
        message.role == .assistant
            && !message.isStreaming
            && !message.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && message.status == nil
            && message.id != model.messages.first?.id
    }

    private func actionRow(_ message: ChatMessageUI) -> some View {
        let busy = model.actionBusyMessageId != nil
        let saved = model.savedMessageIds.contains(message.id)
        let topic = message.relatedConcepts.first ?? model.focusTopic
        return HStack(spacing: 6) {
            Menu {
                Button {
                    Task { await model.createCard(from: message, outputType: .quiz) }
                } label: {
                    Label("Quiz card", systemImage: "questionmark.circle")
                }
                Button {
                    Task { await model.createCard(from: message, outputType: .conceptCard) }
                } label: {
                    Label("Flashcard", systemImage: "rectangle.on.rectangle")
                }
            } label: {
                GRChip(title: "Make cards", systemImage: "plus", style: .outline, compact: true)
            }
            .disabled(busy)

            if let topic {
                GRChip(title: "Quiz me", systemImage: "target", style: .outline, compact: true) {
                    Task { await model.quizMe(on: topic) }
                }
                .disabled(busy)
            }

            GRChip(
                title: saved ? "Saved" : "Save",
                systemImage: saved ? "bookmark.fill" : "bookmark",
                style: saved ? .tinted(.accent) : .outline,
                compact: true
            ) {
                Task { await model.saveMessage(message) }
            }
            .disabled(busy || saved)

            Spacer(minLength: 0)

            if busy {
                ProgressView().controlSize(.mini).tint(GRColor.accent)
            }

            Button {
                UIPasteboard.general.string = message.content
                model.showBanner("Copied answer")
                GRHaptics.tap()
            } label: {
                Image(systemName: "doc.on.doc")
                    .font(.system(size: 13))
                    .foregroundStyle(GRColor.textTertiary)
                    .frame(width: 28, height: 28)
            }
            .accessibilityLabel("Copy answer")
        }
    }

    private var suggestionsRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(model.suggestions, id: \.self) { tip in
                    GRChip(title: tip, style: .outline) {
                        model.sendSuggestion(tip)
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 6)
        }
    }

    // MARK: - Sources

    private struct SourceGroup: Identifiable {
        let source: ChatSourceRef
        let excerptCount: Int
        var id: String { source.id }
    }

    /// Excerpts from the same note arrive as separate sources; show one row per note.
    private static func sourceGroups(_ sources: [ChatSourceRef]) -> [SourceGroup] {
        var order: [String] = []
        var byTitle: [String: [ChatSourceRef]] = [:]
        for source in sources {
            let key = source.title.lowercased()
            if byTitle[key] == nil { order.append(key) }
            byTitle[key, default: []].append(source)
        }
        return order.compactMap { key in
            guard let group = byTitle[key], let first = group.first else { return nil }
            let excerpts = group
                .compactMap { $0.content?.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
            let merged = ChatSourceRef(
                stableId: first.stableId,
                title: first.title,
                content: excerpts.isEmpty ? nil : excerpts.joined(separator: "\n\n· · ·\n\n")
            )
            return SourceGroup(source: merged, excerptCount: group.count)
        }
    }

    private static func mergedSource(for source: ChatSourceRef, in sources: [ChatSourceRef]) -> ChatSourceRef {
        sourceGroups(sources).first { $0.source.title.lowercased() == source.title.lowercased() }?.source ?? source
    }

    // MARK: - Composer

    private func composer(input: Binding<String>) -> some View {
        HStack(alignment: .bottom, spacing: 6) {
            if inputFocused {
                Button {
                    inputFocused = false
                } label: {
                    Image(systemName: "keyboard.chevron.compact.down")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(GRColor.textSecondary)
                        .frame(width: 36, height: 36)
                }
                .accessibilityLabel("Hide keyboard")
                .transition(.scale.combined(with: .opacity))
            }

            TextField(model.focusTopic.map { "Ask about \($0)…" } ?? "Ask your graph…", text: input, axis: .vertical)
                .lineLimit(1...5)
                .focused($inputFocused)
                .font(GRType.body)
                .foregroundStyle(GRColor.textPrimary)
                .padding(.leading, inputFocused ? 2 : 14)
                .padding(.vertical, 11)

            Button {
                Task { await toggleDictation() }
            } label: {
                Image(systemName: dictation.isRecording ? "waveform" : "mic.fill")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(dictation.isRecording ? GRColor.accent : GRColor.textTertiary)
                    .symbolEffect(.variableColor.iterative, isActive: dictation.isRecording)
                    .frame(width: 36, height: 36)
            }
            .accessibilityLabel(dictation.isRecording ? "Stop dictation" : "Dictate question")

            if model.isStreaming {
                // Stop lives where the thumb already is, in place of Send.
                Button {
                    model.cancelStream()
                    GRHaptics.tap()
                } label: {
                    Image(systemName: "stop.fill")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(GRColor.textPrimary)
                        .frame(width: 36, height: 36)
                        .background(Circle().fill(GRColor.fillMuted))
                }
                .accessibilityLabel("Stop answer")
            } else {
                Button {
                    dictation.stop()
                    GRHaptics.tap()
                    Task { await model.send() }
                } label: {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(model.canSend ? .white : GRColor.textTertiary)
                        .frame(width: 36, height: 36)
                        .background {
                            if model.canSend {
                                GRAccentGlass(shape: Circle(), strength: 0.46)
                            } else {
                                Circle().fill(GRColor.fillSubtle)
                            }
                        }
                }
                .disabled(!model.canSend)
                .accessibilityLabel("Send")
            }
        }
        .padding(5)
        .grGlassEffect(.interactive, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .padding(.horizontal, router.isKeyboardVisible ? 12 : 20)
        .padding(.top, 8)
        .padding(.bottom, router.isKeyboardVisible ? 8 : 10)
        .animation(.easeOut(duration: 0.18), value: inputFocused)
        .animation(.easeOut(duration: 0.18), value: model.isStreaming)
    }

    private func toggleDictation() async {
        if dictation.isRecording {
            dictation.stop()
            return
        }
        let base = model.input.isEmpty ? "" : model.input + " "
        let target = model
        await dictation.start { text in
            target.input = base + text
        }
        if let err = dictation.errorMessage {
            model.showBanner(err)
        }
    }

    /// Inline markdown; with sources, "[n]" citation markers become links that open the source.
    private static func markdown(_ text: String, linkCitations: Bool) -> AttributedString {
        var source = text
        if linkCitations {
            source = text.replacing(/\[(\d{1,2})\](?!\()/) { match in
                "[\\[\(match.1)\\]](\(citationScheme)://\(match.1))"
            }
        }
        return (try? AttributedString(
            markdown: source,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(text)
    }
}

private struct TypingDots: View {
    var body: some View {
        TimelineView(.animation) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            HStack(spacing: 4) {
                ForEach(0..<3, id: \.self) { i in
                    Circle()
                        .fill(GRColor.accent)
                        .frame(width: 6, height: 6)
                        .opacity(0.3 + 0.7 * max(0, sin(t * 5 - Double(i) * 0.8)))
                }
            }
        }
        .accessibilityLabel("Assistant is typing")
    }
}

private struct SourceDetailSheet: View {
    let source: ChatSourceRef
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                ScrollView {
                    Text(source.content?.isEmpty == false ? (source.content ?? "") : "No excerpt was returned for this source.")
                        .font(GRType.body)
                        .foregroundStyle(GRColor.textPrimary)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(20)
                }
            }
            .navigationTitle(source.title)
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

// MARK: - Conversation history sheet (L6)

private struct ConversationHistorySheet: View {
    @Bindable var model: ChatViewModel

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                Group {
                    if model.isLoadingHistory && model.conversationSummaries.isEmpty {
                        ProgressView()
                            .tint(GRColor.accent)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else if model.conversationSummaries.isEmpty {
                        emptyState
                    } else {
                        listContent
                    }
                }
            }
            .navigationTitle("Chat History")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("New chat") {
                        model.startNewChat()
                    }
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.accent)
                    .disabled(model.isStreaming || model.isLoadingConversation)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        model.showHistory = false
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(GRColor.textTertiary)
                    }
                    .accessibilityLabel("Close")
                }
            }
            .safeAreaInset(edge: .bottom) {
                if model.isLoadingConversation {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small).tint(GRColor.accent)
                        Text("Loading conversation…")
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textSecondary)
                    }
                    .padding(.vertical, 10)
                    .frame(maxWidth: .infinity)
                    .background(GRColor.canvas.opacity(0.92))
                }
            }
        }
        .preferredColorScheme(.dark)
    }

    private var emptyState: some View {
        VStack(spacing: 14) {
            GlassCard(cornerRadius: 16) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("No conversations")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Text(model.historyEmptyCopy ?? "Past chats will show up here.")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                    if let err = model.historyError {
                        Text(err)
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.warning)
                    }
                }
            }
            .padding(.horizontal, 20)

            Button {
                Task { await model.loadHistory() }
            } label: {
                Text("Retry")
            }
            .buttonStyle(GRButtonStyle(kind: .ghost, fullWidth: false, compact: true))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var listContent: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 10) {
                if let err = model.historyError {
                    GRBanner(systemImage: "exclamationmark.triangle.fill", title: "History issue", subtitle: err, tone: .warning)
                }
                ForEach(model.conversationSummaries) { conv in
                    Button {
                        Task { await model.selectConversation(conv.id) }
                    } label: {
                        GRListRow(
                            title: conv.displayTitle,
                            subtitle: conv.lastMessage ?? conv.displaySubtitle,
                            meta: model.conversationId == conv.id ? "Open" : nil,
                            metaColor: GRColor.accent,
                            systemImage: "bubble.left.and.bubble.right.fill",
                            tone: .accent
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(model.isLoadingConversation || model.isStreaming)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
        }
        .refreshable { await model.loadHistory() }
    }
}

#Preview {
    ZStack {
        GRColor.canvas.ignoresSafeArea()
        ChatView()
    }
    .environment(AppRouter())
    .preferredColorScheme(.dark)
}
