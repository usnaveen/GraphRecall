import Foundation
import Observation

extension GRSettingsKey {
    /// Local opt-in for the agent bridge UI (Settings → Agent). Off by default.
    static let agentBridgeEnabled = "graphrecall.agentBridge.enabled"
}

/// Feature gate for everything agent-bridge in the app.
///
/// The UI shows only when **both** are true:
/// 1. the user turned it on in Settings (`GRSettingsKey.agentBridgeEnabled`), and
/// 2. the server has the bridge mounted (`AGENT_BRIDGE_ENABLED=1`; probed via `/api/agent-bridge/keys`).
///
/// `agent_curated` items that the server puts in `/api/feed` are rendered regardless, since the
/// server only emits them when the bridge is on and the user approved them.
@MainActor
@Observable
final class AgentBridgeCapability {
    static let shared = AgentBridgeCapability()

    enum ServerState: Equatable {
        case unknown, enabled, disabled, unreachable
    }

    private(set) var serverState: ServerState = .unknown
    /// Pending agent suggestions — drives the inbox badge in the feed.
    private(set) var pendingCount = 0
    @ObservationIgnored private var lastProbe: Date?
    @ObservationIgnored private let probeTTL: TimeInterval = 300

    /// Previews / UI tests: force the gate open with mock data, no network.
    var previewMode = false

    var locallyEnabled: Bool = UserDefaults.standard.bool(forKey: GRSettingsKey.agentBridgeEnabled) {
        didSet {
            UserDefaults.standard.set(locallyEnabled, forKey: GRSettingsKey.agentBridgeEnabled)
            if locallyEnabled { Task { await refresh(force: true) } }
        }
    }

    var isAvailable: Bool {
        previewMode || (locallyEnabled && serverState == .enabled)
    }

    func refresh(force: Bool = false) async {
        if previewMode {
            serverState = .enabled
            pendingCount = AgentBridgeMocks.pendingItems.count
            return
        }
        guard locallyEnabled else { return }
        if !force, let lastProbe, Date().timeIntervalSince(lastProbe) < probeTTL { return }
        guard await APIClient.shared.hasAuthToken else {
            serverState = .unknown
            return
        }
        do {
            let enabled = try await APIClient.shared.agentBridgeProbe()
            serverState = enabled ? .enabled : .disabled
            lastProbe = Date()
            if enabled { await refreshPendingCount() }
        } catch {
            serverState = .unreachable
        }
    }

    func refreshPendingCount() async {
        guard isAvailable, !previewMode else { return }
        if let items = try? await APIClient.shared.agentFeedItems(status: .pending, limit: 200) {
            pendingCount = items.count
        }
    }

    func setPendingCount(_ n: Int) { pendingCount = max(n, 0) }

    #if DEBUG
    static func preview() -> AgentBridgeCapability {
        let c = AgentBridgeCapability()
        c.previewMode = true
        c.serverState = .enabled
        c.pendingCount = AgentBridgeMocks.pendingItems.count
        return c
    }
    #endif
}
