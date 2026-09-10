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

    private var streamTask: Task<Void, Never>?

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
            errorMessage = error.localizedDescription
            updateAssistant(assistantId) { msg in
                if msg.content.isEmpty {
                    msg.content = "Sorry — I couldn’t reach the chat stream. \(error.localizedDescription)"
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
