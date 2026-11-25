import Foundation
import Observation

/// Network surface the store needs; swapped for mocks in previews/tests.
struct AgentAskTransport: Sendable {
    var create: @Sendable (_ question: String, _ conversationId: String?, _ context: [String: String]) async throws -> AgentRequest
    var fetch: @Sendable (_ id: String) async throws -> AgentRequest
    var cancel: @Sendable (_ id: String) async throws -> AgentRequest

    static let live = AgentAskTransport(
        create: { q, conv, ctx in try await APIClient.shared.askAgent(question: q, conversationId: conv, context: ctx).request },
        fetch: { id in try await APIClient.shared.agentRequest(id: id) },
        cancel: { id in try await APIClient.shared.cancelAgentRequest(id: id) }
    )
}

/// Tracks "Ask my agent" hand-offs: creates the request, polls until it is terminal,
/// and gives up politely after `clientTimeout` (the answer can still arrive later).
@MainActor
@Observable
final class AgentAskStore {
    struct Tracked: Identifiable, Equatable {
        enum Phase: Equatable {
            case sending
            case waiting           // server queued / claimed
            case answered
            case failed(String)    // agent reported an error, or the request expired/was cancelled
            case timedOut          // stopped polling locally; may still be answered later
            case sendFailed(String)
        }

        let id: String             // local id until the server assigns one
        var serverId: String?
        var question: String
        var request: AgentRequest?
        var phase: Phase
        var startedAt: Date
        var consecutiveErrors = 0

        var isActive: Bool { phase == .sending || phase == .waiting }
    }

    /// Hand-offs shown in the current chat, oldest first.
    var tracked: [Tracked] = []

    @ObservationIgnored private let transport: AgentAskTransport
    @ObservationIgnored private var pollTasks: [String: Task<Void, Never>] = [:]
    @ObservationIgnored let clientTimeout: TimeInterval

    private static let persistKey = "graphrecall.agentBridge.trackedRequestIds"

    init(transport: AgentAskTransport = .live, clientTimeout: TimeInterval = 15 * 60) {
        self.transport = transport
        self.clientTimeout = clientTimeout
    }

    /// Hands a question to the agent. `context` must stay small and user-visible.
    func ask(_ question: String, conversationId: String?, context: [String: String] = [:]) {
        let text = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let localId = UUID().uuidString
        tracked.append(Tracked(id: localId, question: text, phase: .sending, startedAt: Date()))
        send(localId, text: text, conversationId: conversationId, context: context)
    }

    /// Retry a hand-off whose POST failed (e.g. after a 429).
    func retrySend(_ localId: String) {
        guard let t = tracked.first(where: { $0.id == localId }), t.serverId == nil else { return }
        update(localId) { $0.phase = .sending; $0.startedAt = Date() }
        send(localId, text: t.question, conversationId: nil, context: [:])
    }

    private func send(_ localId: String, text: String, conversationId: String?, context: [String: String]) {
        pollTasks[localId]?.cancel()
        pollTasks[localId] = Task { [weak self] in
            guard let self else { return }
            do {
                let req: AgentRequest
                do {
                    req = try await self.transport.create(text, conversationId, context)
                } catch where conversationId != nil && AgentBridgeErrorCopy.isConversationNotFound(error) {
                    // Chat not persisted server-side yet (or not ours): hand off without linking it.
                    req = try await self.transport.create(text, nil, context)
                }
                self.update(localId) {
                    $0.serverId = req.id
                    $0.request = req
                    $0.phase = Self.phase(for: req)
                }
                self.remember(req.id)
                await self.poll(localId)
            } catch {
                self.update(localId) { $0.phase = .sendFailed(AgentBridgeErrorCopy.message(error, action: .ask)) }
            }
        }
    }

    /// Re-check a timed-out hand-off (or one restored after relaunch).
    func refresh(_ localId: String) {
        guard let t = tracked.first(where: { $0.id == localId }), t.serverId != nil else { return }
        update(localId) {
            $0.phase = .waiting
            $0.startedAt = Date()
            $0.consecutiveErrors = 0
        }
        pollTasks[localId]?.cancel()
        pollTasks[localId] = Task { [weak self] in await self?.poll(localId) }
    }

    func cancel(_ localId: String) {
        pollTasks[localId]?.cancel()
        pollTasks[localId] = nil
        guard let serverId = tracked.first(where: { $0.id == localId })?.serverId else {
            tracked.removeAll { $0.id == localId }
            return
        }
        Task { [weak self] in
            guard let self else { return }
            do {
                let req = try await self.transport.cancel(serverId)
                self.update(localId) { $0.request = req; $0.phase = .failed("Cancelled") }
            } catch {
                // 404 means it already finished; fetch the final state instead.
                if let req = try? await self.transport.fetch(serverId) {
                    self.update(localId) { $0.request = req; $0.phase = Self.phase(for: req) }
                }
            }
            self.forget(serverId)
        }
    }

    func dismiss(_ localId: String) {
        pollTasks[localId]?.cancel()
        pollTasks[localId] = nil
        if let serverId = tracked.first(where: { $0.id == localId })?.serverId { forget(serverId) }
        tracked.removeAll { $0.id == localId }
    }

    /// Restore hand-offs that were still pending when the app was closed.
    /// TODO(agent-bridge-ios): scope restored requests to the open conversation
    /// (`conversation_id`) once chat history renders agent answers inline.
    func restore() {
        let ids = UserDefaults.standard.stringArray(forKey: Self.persistKey) ?? []
        for serverId in ids where !tracked.contains(where: { $0.serverId == serverId }) {
            let localId = UUID().uuidString
            tracked.append(Tracked(id: localId, serverId: serverId, question: "", phase: .waiting, startedAt: Date()))
            pollTasks[localId] = Task { [weak self] in await self?.poll(localId) }
        }
    }

    func stopAll() {
        pollTasks.values.forEach { $0.cancel() }
        pollTasks.removeAll()
    }

    // MARK: - Polling

    /// 3s for the first minute, 10s up to 10 minutes, then 30s, until `clientTimeout`.
    nonisolated static func pollInterval(elapsed: TimeInterval) -> TimeInterval {
        switch elapsed {
        case ..<60: return 3
        case ..<600: return 10
        default: return 30
        }
    }

    private func poll(_ localId: String) async {
        while !Task.isCancelled {
            guard let t = tracked.first(where: { $0.id == localId }), let serverId = t.serverId else { return }
            let elapsed = Date().timeIntervalSince(t.startedAt)
            if elapsed >= clientTimeout {
                update(localId) { $0.phase = .timedOut }
                return
            }
            try? await Task.sleep(for: .seconds(min(Self.pollInterval(elapsed: elapsed), clientTimeout - elapsed)))
            guard !Task.isCancelled else { return }
            do {
                let req = try await transport.fetch(serverId)
                let phase = Self.phase(for: req)
                update(localId) {
                    $0.request = req
                    if $0.question.isEmpty { $0.question = req.question }
                    $0.phase = phase
                    $0.consecutiveErrors = 0
                }
                if phase != .waiting {
                    forget(serverId)
                    return
                }
            } catch APIError.http(404, _) {
                update(localId) { $0.phase = .failed("This question no longer exists.") }
                forget(serverId)
                return
            } catch {
                // Transient: keep polling with the same schedule, surface after a few misses.
                update(localId) { $0.consecutiveErrors += 1 }
            }
        }
    }

    /// Maps server state to UI phase. The backend never sweeps stale rows (see review), so a
    /// request past `expires_at` that is still queued/claimed is treated as expired here.
    static func phase(for req: AgentRequest, now: Date = Date()) -> Tracked.Phase {
        switch req.status {
        case .answered: return .answered
        case .failed: return .failed(req.error ?? "Your agent couldn\u{2019}t answer this one.")
        case .cancelled: return .failed("Cancelled")
        // Since cadf9c8 the server sweeps stale rows and fills `error` with the reason.
        case .expired: return .failed(req.error ?? AgentRequestStatus.expired.label)
        case .queued, .claimed, .unknown:
            if let exp = req.expiry, exp <= now { return .failed(AgentRequestStatus.expired.label) }
            return .waiting
        }
    }

    private func update(_ localId: String, _ body: (inout Tracked) -> Void) {
        guard let idx = tracked.firstIndex(where: { $0.id == localId }) else { return }
        body(&tracked[idx])
    }

    private func remember(_ serverId: String) {
        var ids = UserDefaults.standard.stringArray(forKey: Self.persistKey) ?? []
        guard !ids.contains(serverId) else { return }
        ids.append(serverId)
        UserDefaults.standard.set(Array(ids.suffix(20)), forKey: Self.persistKey)
    }

    private func forget(_ serverId: String) {
        var ids = UserDefaults.standard.stringArray(forKey: Self.persistKey) ?? []
        ids.removeAll { $0 == serverId }
        UserDefaults.standard.set(ids, forKey: Self.persistKey)
    }
}

#if DEBUG
extension AgentAskTransport {
    /// Answers after `delay` seconds; questions containing "fail" fail.
    static func mock(delay: TimeInterval = 4) -> AgentAskTransport {
        let start = Date()
        return AgentAskTransport(
            create: { q, conv, _ in
                AgentRequest(id: "mock-\(abs(q.hashValue))", status: .queued, question: q, conversationId: conv)
            },
            fetch: { id in
                let done = Date().timeIntervalSince(start) > delay
                if !done { return AgentRequest(id: id, status: .claimed, question: "") }
                if id.contains("fail") { return AgentBridgeMocks.failed }
                return AgentRequest(id: id, status: .answered, question: "",
                                    answerText: AgentBridgeMocks.answered.answerText,
                                    answerJson: AgentBridgeMocks.answered.answerJson)
            },
            cancel: { id in AgentRequest(id: id, status: .cancelled, question: "") }
        )
    }
}

extension AgentAskStore {
    static func preview() -> AgentAskStore {
        let store = AgentAskStore(transport: .mock())
        store.tracked = [
            Tracked(id: "p1", serverId: "mock-req-1", question: AgentBridgeMocks.answered.question,
                    request: AgentBridgeMocks.answered, phase: .answered, startedAt: Date()),
            Tracked(id: "p2", serverId: "mock-req-2", question: AgentBridgeMocks.researching.question,
                    request: AgentBridgeMocks.researching, phase: .waiting, startedAt: Date()),
            Tracked(id: "p3", serverId: "mock-req-3", question: AgentBridgeMocks.failed.question,
                    request: AgentBridgeMocks.failed, phase: .failed(AgentBridgeMocks.failed.error ?? ""), startedAt: Date()),
            Tracked(id: "p4", serverId: "mock-req-4", question: "Summarise this week's Substack reading.",
                    phase: .timedOut, startedAt: Date()),
        ]
        return store
    }
}
#endif
