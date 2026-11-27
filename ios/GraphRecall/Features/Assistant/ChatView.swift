import SwiftUI
import UIKit

struct ChatView: View {
    @State private var model = ChatViewModel()
    /// Agent bridge: "Ask my agent" hand-offs (hidden unless `AgentBridgeCapability.isAvailable`).
    @State private var agentAsk = AgentAskStore()
    private let agentBridge = AgentBridgeCapability.shared
    @State private var dictation = GRDictation()
    @State private var openSource: ChatSourceRef?
    /// Whether the conversation is scrolled to (or near) the latest message.
    @State private var isNearBottom = true
    @FocusState private var inputFocused: Bool
    @State private var expandedRetrieval: Set<String> = []
    @State private var feedbackReasonMessage: ChatMessageUI?
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
                    // The composer floats over the conversation, so messages scroll under real glass.
                    .safeAreaBar(edge: .bottom) {
                        VStack(spacing: 0) {
                            if showsSuggestions {
                                suggestionsRow
                            }
                            composer(input: $bindable.input)
                        }
                    }
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
            await agentBridge.refresh()
            if agentBridge.isAvailable { agentAsk.restore() }
            // UI-QA: `GR_ASK="question"` asks once per launch, for screenshots of a real answer.
            if let question = ProcessInfo.processInfo.environment["GR_ASK"], !ChatAutoAsk.done {
                ChatAutoAsk.done = true
                model.input = question
                await model.send()
            }
        }
        .onChange(of: router.pendingAssistantPrompt) { _, _ in consumeRouter() }
        .onChange(of: model.input) { _, newValue in
            model.schedulePrefetch(for: newValue)
        }
        .onReceive(NotificationCenter.default.publisher(for: .grSessionReady)) { _ in
            Task { await model.loadSuggestions() }
        }
        .onChange(of: router.pendingConversationId) { _, _ in consumeRouter() }
        .onDisappear {
            dictation.stop()
            model.cancelPrefetch()
        }
        .confirmationDialog(
            "What went wrong?",
            isPresented: Binding(
                get: { feedbackReasonMessage != nil },
                set: { if !$0 { feedbackReasonMessage = nil } }
            ),
            titleVisibility: .visible,
            presenting: feedbackReasonMessage
        ) { message in
            ForEach(ChatFeedbackReason.allCases, id: \.self) { reason in
                Button(reason.label) {
                    GRHaptics.tap()
                    Task { await model.submitFeedback(for: message, rating: .down, reason: reason) }
                }
            }
        }
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
        // Only before the first question: a loaded thread of one question and one answer also has
        // two messages, and the chips then sat on top of the answer.
        !model.suggestions.isEmpty
            && !model.messages.contains(where: { $0.role == .user })
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
                    if agentBridge.isAvailable {
                        AgentAskSection(store: agentAsk)
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
            // System scroll-edge fade at the top; the bottom runs under the glass composer.
            .scrollEdgeEffectStyle(.soft, for: .top)
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
                            .frame(width: 22, height: 22)
                    }
                    .buttonStyle(.glass)
                    .buttonBorderShape(.circle)
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
            .onChange(of: model.isStreaming) { wasStreaming, streaming in
                // UI-QA (`GR_ASK`): once the answer finishes, show the question and the answer's start.
                guard wasStreaming, !streaming, ProcessInfo.processInfo.environment["GR_ASK"] != nil,
                      let question = model.messages.dropLast().last else { return }
                Task { @MainActor in
                    try? await Task.sleep(for: .milliseconds(600))
                    proxy.scrollTo(question.id, anchor: .top)
                }
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
            } else if message.retrieval != nil || !sourceGroups.isEmpty || !message.relatedConcepts.isEmpty {
                retrievalHeader(message, sources: sourceGroups.count)
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

            if !message.relatedConcepts.isEmpty && !message.isStreaming {
                VStack(alignment: .leading, spacing: 6) {
                    Text("CONCEPTS IN THIS ANSWER")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    GRFlowLayout(spacing: 6, lineSpacing: 6) {
                        ForEach(message.relatedConcepts, id: \.self) { concept in
                            // Tap: ask the next question about this concept. Hold: see it in the graph.
                            GRChip(title: concept, style: .tinted(.accent), compact: true) {
                                model.focusTopic = concept
                                inputFocused = true
                                GRHaptics.tap()
                            }
                            .contextMenu {
                                Button { router.focusInGraph(concept) } label: {
                                    Label("Show in graph", systemImage: "point.3.connected.trianglepath.dotted")
                                }
                                Button {
                                    model.focusTopic = concept
                                    inputFocused = true
                                } label: {
                                    Label("Ask about \(concept)", systemImage: "sparkles")
                                }
                            }
                        }
                    }
                }
                .padding(.top, 2)
            }

            // Next questions picked from your graph; only under the latest answer.
            if !message.followUps.isEmpty && !message.isStreaming && message.id == model.messages.last?.id {
                VStack(alignment: .leading, spacing: 6) {
                    Text("ASK NEXT")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    ForEach(message.followUps, id: \.self) { followUp in
                        Button {
                            GRHaptics.tap()
                            model.sendFollowUp(followUp)
                        } label: {
                            Label(followUp.text, systemImage: followUp.systemImage)
                                .font(GRType.caption)
                                .multilineTextAlignment(.leading)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.bordered)
                        .buttonBorderShape(.roundedRectangle(radius: 14))
                        .tint(GRColor.accentCyan)
                        .disabled(model.isStreaming)
                        .accessibilityHint(followUp.reason ?? "")
                        .accessibilityIdentifier("chat.followUp.\(followUp.kind)")
                    }
                }
                .padding(.top, 2)
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

            if agentBridge.isAvailable, let question = userQuestion(before: message) {
                GRChip(title: "Ask agent", systemImage: "sparkles", style: .tinted(.cyan), compact: true) {
                    handOffToAgent(question)
                }
                .accessibilityIdentifier("chat.askAgent")
            }

            Spacer(minLength: 0)

            if busy {
                ProgressView().controlSize(.mini).tint(GRColor.accent)
            }

            let rating = model.feedbackRatings[message.id]
            Button {
                GRHaptics.tap()
                Task { await model.submitFeedback(for: message, rating: .up) }
            } label: {
                Image(systemName: rating == .up ? "hand.thumbsup.fill" : "hand.thumbsup")
                    .font(.system(size: 13))
                    .foregroundStyle(rating == .up ? GRColor.accent : GRColor.textTertiary)
                    .frame(width: 28, height: 28)
            }
            .accessibilityLabel("Helpful")

            Button {
                GRHaptics.tap()
                Task { await model.submitFeedback(for: message, rating: .down) }
                feedbackReasonMessage = message
            } label: {
                Image(systemName: rating == .down ? "hand.thumbsdown.fill" : "hand.thumbsdown")
                    .font(.system(size: 13))
                    .foregroundStyle(rating == .down ? GRColor.accent : GRColor.textTertiary)
                    .frame(width: 28, height: 28)
            }
            .accessibilityLabel("Not helpful")

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
                .padding(.vertical, 8)
                .frame(minHeight: 36)

            if agentBridge.isAvailable && model.canSend {
                // Sends the typed question to the user's agent instead of the in-app assistant.
                Button {
                    let text = model.input
                    model.input = ""
                    dictation.stop()
                    GRHaptics.tap()
                    handOffToAgent(text)
                } label: {
                    Image(systemName: "sparkles")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(GRColor.accentCyan)
                        .frame(width: 36, height: 36)
                }
                .accessibilityLabel("Ask my agent")
                .accessibilityIdentifier("chat.composer.askAgent")
                .transition(.scale.combined(with: .opacity))
            }

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
                        .foregroundStyle(GRColor.canvas)
                        .frame(width: 36, height: 36)
                        .background(Circle().fill(GRColor.accent))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Stop answer")
            } else {
                Button {
                    dictation.stop()
                    GRHaptics.tap()
                    Task { await model.send() }
                } label: {
                    // Same 36 pt as the mic and the one-line field, so it sits centred in the bar.
                    Image(systemName: "arrow.up")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(GRColor.canvas)
                        .frame(width: 36, height: 36)
                        .background(Circle().fill(GRColor.accent))
                        .opacity(model.canSend ? 1 : 0.55)
                }
                .buttonStyle(.plain)
                .disabled(!model.canSend)
                .accessibilityLabel("Send")
            }
        }
        .padding(5)
        .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 24))
        .padding(.horizontal, router.isKeyboardVisible ? 12 : 20)
        .padding(.top, 8)
        .padding(.bottom, router.isKeyboardVisible ? 8 : 10)
        .animation(.easeOut(duration: 0.18), value: inputFocused)
        .animation(.easeOut(duration: 0.18), value: model.isStreaming)
    }

    // MARK: - Agent bridge

    /// The user message the given assistant answer replied to.
    private func userQuestion(before message: ChatMessageUI) -> String? {
        guard let idx = model.messages.firstIndex(where: { $0.id == message.id }) else { return nil }
        return model.messages[..<idx].last(where: { $0.role == .user })?.content
    }

    private func handOffToAgent(_ question: String) {
        var context: [String: String] = ["source": "ios_chat"]
        if let topic = model.focusTopic { context["topic"] = topic }
        // TODO(agent-bridge-ios): include scoped note ids / related concept ids once the agent
        // side reads them (keep it small: the server caps context at 8 KB).
        agentAsk.ask(question, conversationId: model.conversationId, context: context)
        model.showBanner("Sent to your agent")
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

    /// One line of an answer for a list: markdown markers ("**", "#", "`") and citations removed.
    static func plainPreview(_ text: String) -> String {
        var s = text.replacing(/[*_`#>]+/, with: "")
        s = s.replacing(/\[\d{1,2}\]/, with: "")
        return s.split(whereSeparator: \.isNewline).joined(separator: " ")
            .replacing(/\ {2,}/, with: " ")
            .trimmingCharacters(in: .whitespaces)
    }

    /// What grounded the answer, as the web chat showed it: "Explain · from 3 notes · 15 concepts",
    /// tap to see which concepts the question was matched to.
    private func retrievalHeader(_ message: ChatMessageUI, sources: Int) -> some View {
        let expanded = expandedRetrieval.contains(message.id)
        let summary = message.retrieval?.summary
            ?? Self.groundingLine(concepts: message.relatedConcepts.count, sources: sources)
        let matched = (message.retrieval?.entities.isEmpty == false)
            ? message.retrieval!.entities : message.relatedConcepts
        return VStack(alignment: .leading, spacing: 4) {
            Button {
                withAnimation(.easeOut(duration: 0.18)) {
                    if expanded { expandedRetrieval.remove(message.id) } else { expandedRetrieval.insert(message.id) }
                }
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: "sparkles")
                    Text(summary)
                    if !matched.isEmpty {
                        Image(systemName: expanded ? "chevron.up" : "chevron.down")
                            .font(.system(size: 8, weight: .bold))
                    }
                }
                .font(GRType.micro)
                .foregroundStyle(GRColor.accent.opacity(0.85))
            }
            .buttonStyle(.plain)
            .disabled(matched.isEmpty)
            if expanded && !matched.isEmpty {
                Text("Matched: " + matched.prefix(8).joined(separator: ", "))
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                    .transition(.opacity)
            }
        }
    }

    /// "Grounded in 15 concepts · 2 sources", leaving out a count of zero.
    private static func groundingLine(concepts: Int, sources: Int) -> String {
        var parts: [String] = []
        if concepts > 0 { parts.append("\(concepts) concept\(concepts == 1 ? "" : "s")") }
        if sources > 0 { parts.append("\(sources) source\(sources == 1 ? "" : "s")") }
        return "Grounded in " + parts.joined(separator: " · ")
    }

    /// Inline markdown; with sources, "[n]" citation markers become links that open the source.
    /// Headings ("### Why it is faster") become bold lines: inline parsing would print the hashes.
    private static func markdown(_ text: String, linkCitations: Bool) -> AttributedString {
        // Math first, so `_` and `*` inside it aren't read as emphasis and `\[…\]` isn't a citation.
        let (withoutMath, mathSpans) = ChatMarkdown.stashMath(text)
        var source = withoutMath.replacing(/(?m)^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t#]*$/) { match in
            "**\(match.1)**"
        }
        // Horizontal rules ("---", "***", "___") become a divider; inline parsing would print them.
        source = source.replacing(/(?m)^[ \t]{0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$/) { _ in
            String(ChatMarkdown.divider)
        }
        // List markers ("* ", "- ", "+ ") become bullets: inline parsing would print them as-is.
        source = source.replacing(/(?m)^([ \t]*)[*+-][ \t]+/) { match in "\(match.1)• " }
        if linkCitations {
            source = source.replacing(/\[(\d{1,2})\](?!\()/) { match in
                "[\\[\(match.1)\\]](\(citationScheme)://\(match.1))"
            }
        }
        var attr = (try? AttributedString(
            markdown: source,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(source)
        ChatMarkdown.style(&attr, math: mathSpans)
        return attr
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
            .grButton(.ghost, fullWidth: false, compact: true)
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
                            subtitle: conv.lastMessage.map(ChatView.plainPreview) ?? conv.displaySubtitle,
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

// MARK: - Math and colour in answers

/// Readable math in chat answers. The model writes LaTeX (`$h_{t-1}$`, `$\frac{QK^T}{\sqrt{d_k}}$`);
/// this turns it into Unicode (hₜ₋₁, QKᵀ/√dₖ) so it reads naturally while the answer streams, with no
/// web view. Anything it can't map stays readable (`W_Q` keeps its underscore).
enum ChatMath {
    private static let named: [String: String] = [
        // Greek
        "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε",
        "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
        "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ",
        "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
        "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
        "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
        // Operators and relations
        "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓", "sum": "∑", "prod": "∏",
        "int": "∫", "sqrt": "√", "infty": "∞", "partial": "∂", "nabla": "∇", "leq": "≤", "le": "≤",
        "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠", "approx": "≈", "sim": "∼", "propto": "∝",
        "equiv": "≡", "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆", "cup": "∪",
        "cap": "∩", "forall": "∀", "exists": "∃", "to": "→", "rightarrow": "→", "leftarrow": "←",
        "Rightarrow": "⇒", "implies": "⇒", "iff": "⇔", "mapsto": "↦", "ldots": "…", "cdots": "⋯",
        "dots": "…", "top": "ᵀ", "intercal": "ᵀ", "odot": "⊙", "otimes": "⊗", "oplus": "⊕",
        "circ": "∘", "langle": "⟨", "rangle": "⟩", "lVert": "‖", "rVert": "‖", "|": "‖",
        "log": "log", "exp": "exp", "max": "max", "min": "min", "arg": "arg", "argmax": "argmax",
        "softmax": "softmax", "sin": "sin", "cos": "cos", "tanh": "tanh", "lim": "lim",
        // Layout-only commands
        "left": "", "right": "", "big": "", "Big": "", "bigg": "", "quad": " ", "qquad": "  ",
        "displaystyle": "", "limits": "",
    ]

    private static let superscripts: [Character: Character] = [
        "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
        "+": "⁺", "-": "⁻", "−": "⁻", "=": "⁼", "(": "⁽", ")": "⁾", "a": "ᵃ", "b": "ᵇ", "c": "ᶜ",
        "d": "ᵈ", "e": "ᵉ", "f": "ᶠ", "g": "ᵍ", "h": "ʰ", "i": "ⁱ", "j": "ʲ", "k": "ᵏ", "l": "ˡ",
        "m": "ᵐ", "n": "ⁿ", "o": "ᵒ", "p": "ᵖ", "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ", "v": "ᵛ",
        "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ", "T": "ᵀ", "A": "ᴬ", "B": "ᴮ", "D": "ᴰ", "E": "ᴱ",
        "G": "ᴳ", "H": "ᴴ", "I": "ᴵ", "J": "ᴶ", "K": "ᴷ", "L": "ᴸ", "M": "ᴹ", "N": "ᴺ", "O": "ᴼ",
        "P": "ᴾ", "R": "ᴿ", "U": "ᵁ", "V": "ⱽ", "W": "ᵂ", "*": "*", "'": "′", "ᵀ": "ᵀ",
    ]

    private static let subscripts: [Character: Character] = [
        "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
        "+": "₊", "-": "₋", "−": "₋", "=": "₌", "(": "₍", ")": "₎", "a": "ₐ", "e": "ₑ", "h": "ₕ",
        "i": "ᵢ", "j": "ⱼ", "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ",
        "s": "ₛ", "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ",
    ]

    static func render(_ latex: String) -> String {
        var s = latex.trimmingCharacters(in: .whitespacesAndNewlines)
        // Text-like wrappers keep their contents.
        s = s.replacing(/\\(?:text|mathrm|mathbf|mathit|mathcal|operatorname|textbf|textit|boldsymbol|mathbb)\{([^{}]*)\}/) {
            String($0.1)
        }
        // Accents.
        s = s.replacing(/\\hat\{([^{}]*)\}/) { "\($0.1)\u{0302}" }
        s = s.replacing(/\\(?:bar|overline)\{([^{}]*)\}/) { "\($0.1)\u{0304}" }
        s = s.replacing(/\\vec\{([^{}]*)\}/) { "\($0.1)\u{20D7}" }
        s = s.replacing(/\\tilde\{([^{}]*)\}/) { "\($0.1)\u{0303}" }
        // Spacing commands like \, \; \!
        s = s.replacing(/\\[,;:! ]/) { _ in " " }
        // Sub- and superscripts first (single characters, then braced groups), so the fractions and
        // roots below see plain text inside their braces.
        s = s.replacing(/\^([A-Za-z0-9+\-=()*'])/) { m in mapped(String(m.1), superscripts) ?? "^\(m.1)" }
        s = s.replacing(/_([A-Za-z0-9])/) { m in mapped(String(m.1), subscripts) ?? "_\(m.1)" }
        s = s.replacing(/\^\{([^{}]*)\}/) { m in mapped(String(m.1), superscripts) ?? "^(\(m.1))" }
        s = s.replacing(/_\{([^{}]*)\}/) { m in mapped(String(m.1), subscripts) ?? "_(\(m.1))" }
        // Fractions and roots, innermost first.
        for _ in 0..<4 {
            s = s.replacing(/\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}/) { "\(wrap(String($0.1)))/\(wrap(String($0.2)))" }
            s = s.replacing(/\\sqrt\{([^{}]*)\}/) { "√\(wrap(String($0.1)))" }
        }
        // Named commands (\alpha, \times, \log …). Unknown ones lose their backslash.
        s = s.replacing(/\\([A-Za-z]+|\|)/) { named[String($0.1)] ?? String($0.1) }
        s = s.replacingOccurrences(of: "{", with: "").replacingOccurrences(of: "}", with: "")
        s = s.replacing(/\s+/) { _ in " " }
        return s.trimmingCharacters(in: .whitespaces)
    }

    private static func mapped(_ text: String, _ table: [Character: Character]) -> String? {
        var out = ""
        for ch in text where ch != " " {
            guard let m = table[ch] else { return nil }
            out.append(m)
        }
        return out
    }

    /// Parenthesise anything longer than one symbol, so a/b stays unambiguous.
    private static func wrap(_ s: String) -> String {
        let t = s.trimmingCharacters(in: .whitespaces)
        return t.count <= 1 || t.allSatisfy({ $0.isLetter || $0.isNumber }) ? t : "(\(t))"
    }
}

/// Colour for chat answers: bold terms in the accent green, math in blue, inline code in violet,
/// italics softly warm. Citations keep the cyan link tint set on the Text.
enum ChatMarkdown {
    static let mathColor = Color(red: 0.49, green: 0.74, blue: 1.0)
    static let codeColor = Color(red: 0.77, green: 0.71, blue: 0.99)
    static let emphasisColor = Color(red: 1.0, green: 0.82, blue: 0.55)

    private static let open: Character = "\u{E000}"
    private static let close: Character = "\u{E001}"
    /// Placeholder for a markdown horizontal rule, drawn as a thin line.
    static let divider: Character = "\u{E002}"

    /// Pulls math spans out before markdown parsing (so `_` and `*` inside them aren't read as
    /// emphasis) and leaves private-use placeholders where they were.
    static func stashMath(_ text: String) -> (String, [String]) {
        var spans: [String] = []
        func token(_ latex: Substring) -> String {
            spans.append(ChatMath.render(String(latex)))
            return "\(open)\(spans.count - 1)\(close)"
        }
        var s = text
        s = s.replacing(/\$\$([\s\S]+?)\$\$/) { token($0.1) }
        s = s.replacing(/\\\[([\s\S]+?)\\\]/) { token($0.1) }
        s = s.replacing(/\\\(([\s\S]+?)\\\)/) { token($0.1) }
        s = stashInlineDollars(s, token: token)
        return (s, spans)
    }

    /// `$…$` on one line, opening $ followed by a non-space, closing $ preceded by a non-space and
    /// not followed by a digit, so prices like "$5 and $10" stay as they are.
    private static func stashInlineDollars(_ s: String, token: (Substring) -> String) -> String {
        var out = ""
        var i = s.startIndex
        while i < s.endIndex {
            let ch = s[i]
            let escaped = i > s.startIndex && s[s.index(before: i)] == "\\"
            if ch == "$", !escaped {
                let start = s.index(after: i)
                if start < s.endIndex, !s[start].isWhitespace, !s[start].isNumber {
                    var j = start
                    var found: String.Index?
                    while j < s.endIndex, s[j] != "\n" {
                        if s[j] == "$", !s[s.index(before: j)].isWhitespace {
                            let after = s.index(after: j)
                            if after == s.endIndex || !s[after].isNumber { found = j }
                            break
                        }
                        j = s.index(after: j)
                    }
                    if let end = found {
                        out += token(s[start..<end])
                        i = s.index(after: end)
                        continue
                    }
                }
            }
            out.append(ch)
            i = s.index(after: i)
        }
        return out
    }

    /// Colours emphasis and code runs, then swaps the math placeholders for styled math.
    static func style(_ attr: inout AttributedString, math spans: [String]) {
        for run in attr.runs where run.link == nil {
            guard let intent = run.inlinePresentationIntent else { continue }
            if intent.contains(.stronglyEmphasized) {
                attr[run.range].foregroundColor = GRColor.accent
            } else if intent.contains(.code) {
                attr[run.range].foregroundColor = codeColor
                attr[run.range].font = .system(.callout, design: .monospaced)
            } else if intent.contains(.emphasized) {
                attr[run.range].foregroundColor = emphasisColor
            }
        }
        while let rule = attr.range(of: String(divider)) {
            var line = AttributedString(String(repeating: "─", count: 22))
            line.foregroundColor = GRColor.textTertiary
            attr.replaceSubrange(rule, with: line)
        }
        while let start = attr.range(of: String(open)),
              let end = attr[start.upperBound...].range(of: String(close)) {
            let index = Int(String(attr[start.upperBound..<end.lowerBound].characters)) ?? -1
            var math = AttributedString(spans.indices.contains(index) ? spans[index] : "")
            math.foregroundColor = mathColor
            math.font = .system(.body, design: .serif)
            attr.replaceSubrange(start.lowerBound..<end.upperBound, with: math)
        }
    }
}

@MainActor
private enum ChatAutoAsk {
    static var done = false
}
