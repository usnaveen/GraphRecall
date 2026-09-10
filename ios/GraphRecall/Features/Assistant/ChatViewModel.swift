import Foundation
import Observation

@MainActor
@Observable
final class ChatViewModel {
    var messages: [ChatMessageUI] = []
    var input: String = ""
    var suggestions: [String] = []
    var conversationId: String?
    var isStreaming = false
    var statusLine: String?
    var errorMessage: String?
    var usingStub = false

    /// Soft success banner after create-card / save (clears itself).
    var bannerMessage: String?
    /// Which assistant bubble has the Add-to-Feed picker expanded.
    var addToFeedMessageId: String?
    /// Message id currently running create-card / save.
    var actionBusyMessageId: String?
    var savedMessageIds: Set<String> = []

    /// Conversation history sheet (L6).
    var showHistory = false
    var conversationSummaries: [ChatConversationSummary] = []
    var isLoadingHistory = false
    var isLoadingConversation = false
    var historyError: String?
    /// Soft empty-state when offline / unsigned — never HTML.
    var historyEmptyCopy: String?

    private var streamTask: Task<Void, Never>?
    private var bannerTask: Task<Void, Never>?

    var canSend: Bool {
        !input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isStreaming
    }

    func onAppear() async {
        if messages.isEmpty {
            messages = [
                ChatMessageUI(
                    role: .assistant,
                    content: "Ask anything about your knowledge graph — I’ll stream GraphRAG answers here."
                )
            ]
        }
        await loadSuggestions()
    }

    func loadSuggestions() async {
        do {
            let hasAuth = await APIClient.shared.hasAuthToken
            guard hasAuth else {
                suggestions = [
                    "What topics should I review today?",
                    "Explain my weakest concepts",
                    "Compare related ideas in my graph"
                ]
                usingStub = true
                return
            }
            suggestions = try await APIClient.shared.fetchChatSuggestions()
            usingStub = false
        } catch {
            suggestions = [
                "What topics should I review today?",
                "Explain my weakest concepts",
                "Quiz me on my graph"
            ]
        }
    }

    func sendSuggestion(_ text: String) {
        input = text
        Task { await send() }
    }

    func send() async {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isStreaming else { return }

        input = ""
        errorMessage = nil
        messages.append(ChatMessageUI(role: .user, content: text))

        let assistantId = UUID().uuidString
        messages.append(
            ChatMessageUI(
                id: assistantId,
                role: .assistant,
                content: "",
                status: "Thinking…",
                isStreaming: true
            )
        )
        isStreaming = true
        statusLine = "Thinking…"

        streamTask?.cancel()
        streamTask = Task { await runStream(assistantId: assistantId, text: text) }
        await streamTask?.value
    }

    func cancelStream() {
        streamTask?.cancel()
        streamTask = nil
        isStreaming = false
        statusLine = nil
        if let idx = messages.lastIndex(where: { $0.isStreaming }) {
            messages[idx].isStreaming = false
            messages[idx].status = "Cancelled"
        }
    }

    func toggleAddToFeed(for messageId: String) {
        if addToFeedMessageId == messageId {
            addToFeedMessageId = nil
        } else {
            addToFeedMessageId = messageId
        }
    }

    func createCard(from message: ChatMessageUI, outputType: CreateCardOutputType) async {
        guard actionBusyMessageId == nil else { return }
        guard !message.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        actionBusyMessageId = message.id
        defer { actionBusyMessageId = nil }

        let topic = message.relatedConcepts.first

        if let serverId = message.serverId, !serverId.isEmpty {
            do {
                let result = try await APIClient.shared.createCardFromMessage(
                    messageId: serverId,
                    outputType: outputType,
                    topic: topic
                )
                let item = result.asFeedItem()
                await OfflineReviewStore.shared.ingestFeedItem(item)
                NotificationCenter.default.post(name: .grFeedShouldReload, object: nil)
                NotificationCenter.default.post(name: .grDumpCompleted, object: nil)
                addToFeedMessageId = nil
                showBanner("\(outputType.feedLabel) added to Feed")
            } catch {
                errorMessage = APIError.userFacing(error, resource: "chat")
            }
            return
        }

        // Offline stub / missing server id — local Demo-style card still useful.
        let local = ChatLocalFeedFactory.makeLocalCard(from: message, outputType: outputType)
        await OfflineReviewStore.shared.ingestFeedItem(local)
        NotificationCenter.default.post(name: .grFeedShouldReload, object: nil)
        NotificationCenter.default.post(name: .grDumpCompleted, object: nil)
        addToFeedMessageId = nil
        showBanner("\(outputType.feedLabel) saved locally — check Feed")
    }

    func saveMessage(_ message: ChatMessageUI, topic: String? = nil) async {
        guard actionBusyMessageId == nil else { return }
        guard !message.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        actionBusyMessageId = message.id
        defer { actionBusyMessageId = nil }

        let resolvedTopic = topic ?? message.relatedConcepts.first

        if let serverId = message.serverId, !serverId.isEmpty {
            do {
                _ = try await APIClient.shared.saveChatMessage(messageId: serverId, topic: resolvedTopic)
                savedMessageIds.insert(message.id)
                showBanner("Saved for quiz")
            } catch {
                errorMessage = APIError.userFacing(error, resource: "chat")
            }
            return
        }

        // Offline: still mark locally so the affordance feels complete.
        savedMessageIds.insert(message.id)
        let local = ChatLocalFeedFactory.makeLocalCard(from: message, outputType: .conceptCard)
        await OfflineReviewStore.shared.ingestFeedItem(local)
        NotificationCenter.default.post(name: .grFeedShouldReload, object: nil)
        showBanner("Saved locally for quiz — check Feed")
    }


    // MARK: - Conversation history (L6)

    func openHistory() {
        showHistory = true
        Task { await loadHistory() }
    }

    func loadHistory() async {
        isLoadingHistory = true
        historyError = nil
        historyEmptyCopy = nil
        defer { isLoadingHistory = false }

        let hasAuth = await APIClient.shared.hasAuthToken
        guard hasAuth else {
            conversationSummaries = []
            usingStub = true
            historyEmptyCopy = "Sign in to see past conversations. Offline demo mode keeps this chat local."
            return
        }

        do {
            let response = try await APIClient.shared.getChatHistory()
            conversationSummaries = response.conversations
            usingStub = false
            if conversationSummaries.isEmpty {
                historyEmptyCopy = "No past conversations yet. Send a message to start one."
            }
        } catch {
            conversationSummaries = []
            historyError = APIError.userFacing(error, resource: "chat history")
            historyEmptyCopy = "Couldn’t load history right now. Check your connection and try again."
        }
    }

    func selectConversation(_ id: String) async {
        guard !isStreaming, !isLoadingConversation else { return }
        isLoadingConversation = true
        historyError = nil
        defer { isLoadingConversation = false }

        do {
            let detail = try await APIClient.shared.getConversation(id: id)
            let uiMessages = detail.messages.map { $0.asUIMessage() }
            conversationId = detail.conversation?.id ?? id
            messages = uiMessages.isEmpty
                ? [
                    ChatMessageUI(
                        role: .assistant,
                        content: "This conversation has no messages yet — ask anything about your graph."
                    )
                  ]
                : uiMessages
            savedMessageIds = []
            addToFeedMessageId = nil
            errorMessage = nil
            showHistory = false
            usingStub = false
        } catch {
            historyError = APIError.userFacing(error, resource: "conversation")
        }
    }

    func startNewChat() {
        cancelStream()
        conversationId = nil
        messages = [
            ChatMessageUI(
                role: .assistant,
                content: "Ask anything about your knowledge graph — I’ll stream GraphRAG answers here."
            )
        ]
        savedMessageIds = []
        addToFeedMessageId = nil
        errorMessage = nil
        statusLine = nil
        showHistory = false
        Task { await loadSuggestions() }
    }

    private func showBanner(_ text: String) {
        bannerMessage = text
        bannerTask?.cancel()
        bannerTask = Task {
            try? await Task.sleep(nanoseconds: 2_800_000_000)
            if !Task.isCancelled { bannerMessage = nil }
        }
    }

    private func runStream(assistantId: String, text: String) async {
        let hasAuth = await APIClient.shared.hasAuthToken
        usingStub = !hasAuth

        let events: AsyncThrowingStream<ChatSSEEvent, Error>
        if hasAuth {
            events = await ChatSSEClient.shared.stream(
                message: text,
                conversationId: conversationId,
                accessToken: await APIClient.shared.getAccessToken()
            )
        } else {
            events = await ChatSSEClient.shared.stubStream(message: text)
        }

        do {
            for try await event in events {
                if Task.isCancelled { break }
                apply(event, assistantId: assistantId)
            }
        } catch {
            errorMessage = APIError.userFacing(error, resource: "chat")
            updateAssistant(assistantId) { msg in
                if msg.content.isEmpty {
                    msg.content = "Sorry — I couldn’t reach the chat stream."
                }
                msg.status = nil
                msg.isStreaming = false
            }
        }

        isStreaming = false
        statusLine = nil
        updateAssistant(assistantId) { $0.isStreaming = false; $0.status = nil }
    }

    private func apply(_ event: ChatSSEEvent, assistantId: String) {
        switch event {
        case .status(let status):
            statusLine = status
            updateAssistant(assistantId) { $0.status = status }
        case .chunk(let chunk):
            updateAssistant(assistantId) {
                $0.content += chunk
                $0.status = statusLine
            }
        case .done(let payload):
            if let cid = payload.conversationId {
                conversationId = cid
            }
            updateAssistant(assistantId) { msg in
                msg.sources = payload.sources
                msg.relatedConcepts = payload.relatedConcepts
                msg.serverId = payload.messageId
                msg.isStreaming = false
                msg.status = nil
            }
            statusLine = nil
        case .error(let message):
            errorMessage = message
            updateAssistant(assistantId) {
                if $0.content.isEmpty { $0.content = message }
                $0.isStreaming = false
                $0.status = nil
            }
        case .unknown:
            break
        }
    }

    private func updateAssistant(_ id: String, _ mutate: (inout ChatMessageUI) -> Void) {
        guard let idx = messages.firstIndex(where: { $0.id == id }) else { return }
        var copy = messages[idx]
        mutate(&copy)
        messages[idx] = copy
    }
}
