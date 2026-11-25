import Observation
import SwiftUI

/// Approval inbox for cards the user's agent suggested (`agent_feed_items`, status `pending`).
/// Nothing reaches `/api/feed` until it is approved here.
@MainActor
@Observable
final class AgentInboxViewModel {
    enum Filter: String, CaseIterable, Identifiable {
        case pending, approved, rejected
        var id: String { rawValue }
        var title: String { rawValue.capitalized }
        var status: AgentFeedItemStatus {
            switch self {
            case .pending: return .pending
            case .approved: return .approved
            case .rejected: return .rejected
            }
        }
    }

    var filter: Filter = .pending
    var items: [AgentFeedItem] = []
    var isLoading = false
    var errorMessage: String?
    var busyIds: Set<String> = []
    var toast: String?

    @ObservationIgnored private let useMocks: Bool
    @ObservationIgnored private var toastTask: Task<Void, Never>?

    init(useMocks: Bool = false) {
        self.useMocks = useMocks
        if useMocks { items = AgentBridgeMocks.pendingItems }
    }

    func load() async {
        if useMocks {
            items = AgentBridgeMocks.pendingItems.filter { filter == .pending || $0.status == filter.status }
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            items = try await APIClient.shared.agentFeedItems(status: filter.status)
            errorMessage = nil
            if filter == .pending { AgentBridgeCapability.shared.setPendingCount(items.count) }
        } catch {
            errorMessage = APIError.userFacing(error, resource: "agent suggestions")
        }
    }

    func approve(_ item: AgentFeedItem) async { await decide(item, approve: true) }
    func reject(_ item: AgentFeedItem) async { await decide(item, approve: false) }

    /// Approves every visible pending item. Sequential so a failure stops the batch.
    func approveAll() async {
        for item in items where item.status == .pending {
            await decide(item, approve: true)
            if errorMessage != nil { break }
        }
    }

    private func decide(_ item: AgentFeedItem, approve: Bool) async {
        guard !busyIds.contains(item.id) else { return }
        busyIds.insert(item.id)
        defer { busyIds.remove(item.id) }
        // Optimistic removal from the pending list; restored on failure.
        let snapshot = items
        if filter == .pending { items.removeAll { $0.id == item.id } }
        if useMocks {
            showToast(approve ? "Added to your feed" : "Dismissed")
            return
        }
        do {
            if approve {
                _ = try await APIClient.shared.approveAgentFeedItem(id: item.id)
            } else {
                _ = try await APIClient.shared.rejectAgentFeedItem(id: item.id)
            }
            errorMessage = nil
            showToast(approve ? "Added to your feed" : "Dismissed")
            if filter == .pending { AgentBridgeCapability.shared.setPendingCount(items.count) }
            if approve { NotificationCenter.default.post(name: .grFeedShouldReload, object: nil) }
        } catch where AgentBridgeErrorCopy.statusCode(error) == 409 || AgentBridgeErrorCopy.statusCode(error) == 404 {
            // Already approved/dismissed (or gone): keep it out of the list and resync.
            showToast(AgentBridgeErrorCopy.message(error, action: approve ? .approve : .reject))
            await load()
        } catch {
            items = snapshot
            errorMessage = AgentBridgeErrorCopy.message(error, action: approve ? .approve : .reject)
        }
    }

    private func showToast(_ text: String) {
        toast = text
        toastTask?.cancel()
        toastTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            self?.toast = nil
        }
    }
}

struct AgentInboxView: View {
    @State private var model: AgentInboxViewModel
    @Environment(\.dismiss) private var dismiss

    init(model: AgentInboxViewModel = AgentInboxViewModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        @Bindable var bindable = model
        NavigationStack {
            ZStack(alignment: .bottom) {
                GRColor.canvas.ignoresSafeArea()
                GRBackdropGlow(tint: GRColor.accentCyan, offset: CGSize(width: 140, height: -260))

                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        Picker("Filter", selection: $bindable.filter) {
                            ForEach(AgentInboxViewModel.Filter.allCases) { Text($0.title).tag($0) }
                        }
                        .pickerStyle(.segmented)

                        if let error = model.errorMessage {
                            GRBanner(systemImage: "exclamationmark.triangle.fill", title: "Couldn\u{2019}t update", subtitle: error, tone: .warning)
                        }

                        if model.isLoading && model.items.isEmpty {
                            ProgressView().tint(GRColor.accent).frame(maxWidth: .infinity).padding(.top, 40)
                        } else if model.items.isEmpty {
                            emptyState
                        } else {
                            ForEach(model.items) { item in
                                AgentSuggestionCard(
                                    item: item,
                                    busy: model.busyIds.contains(item.id),
                                    showsActions: item.status == .pending,
                                    onApprove: { Task { await model.approve(item) } },
                                    onReject: { Task { await model.reject(item) } }
                                )
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 8)
                    .padding(.bottom, 32)
                }
                .refreshable { await model.load() }

                if let toast = model.toast {
                    GRToast(message: toast)
                        .padding(.bottom, 20)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .animation(.easeOut(duration: 0.2), value: model.toast)
            .navigationTitle("From your agent")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
                if model.filter == .pending && model.items.count > 1 {
                    ToolbarItem(placement: .primaryAction) {
                        Button("Approve all") { Task { await model.approveAll() } }
                    }
                }
            }
        }
        .task { await model.load() }
        .onChange(of: model.filter) { _, _ in Task { await model.load() } }
    }

    private var emptyState: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                Text(model.filter == .pending ? "Nothing waiting" : "Nothing here yet")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.accent)
                Text(model.filter == .pending
                     ? "Your agent curates overnight. New suggestions show up here for you to approve before they reach your feed."
                     : "Items you \(model.filter == .approved ? "approve" : "dismiss") will be listed here.")
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)
            }
        }
    }
}

/// One suggestion: badge, title, summary, the agent's rationale, the source host, actions.
/// Every agent-provided string is rendered with `Text(verbatim:)` — no markdown, no links.
struct AgentSuggestionCard: View {
    let item: AgentFeedItem
    var busy = false
    var showsActions = true
    var onApprove: () -> Void = {}
    var onReject: () -> Void = {}

    @State private var showBack = false

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    AgentProvenanceBadge(compact: true)
                    Text(item.itemKind.replacingOccurrences(of: "_", with: " ").uppercased())
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    Spacer(minLength: 0)
                    if let date = item.target {
                        Text(date, format: .dateTime.weekday(.abbreviated).day().month(.abbreviated))
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textTertiary)
                    }
                }

                Text(verbatim: item.title)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                Text(verbatim: item.summary)
                    .font(.subheadline)
                    .foregroundStyle(GRColor.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)

                if let fc = item.flashcard {
                    Button { showBack.toggle() } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(verbatim: fc.front)
                                .font(GRType.caption.weight(.semibold))
                                .foregroundStyle(GRColor.textPrimary)
                            if showBack {
                                Text(verbatim: fc.back)
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.textSecondary)
                            } else {
                                Text("Tap to preview the answer")
                                    .font(GRType.micro)
                                    .foregroundStyle(GRColor.textTertiary)
                            }
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }

                AgentReasonRow(reason: item.reason)

                AgentSourceLink(kind: item.sourceKind, url: item.safeSourceURL)

                if showsActions {
                    HStack(spacing: 10) {
                        Button(action: onReject) {
                            Label("Dismiss", systemImage: "xmark")
                        }
                        .grButton(.secondary, compact: true)
                        .accessibilityIdentifier("agent.reject")

                        Button(action: onApprove) {
                            Label("Add to feed", systemImage: "checkmark")
                        }
                        .grButton(.primary, compact: true)
                        .accessibilityIdentifier("agent.approve")
                    }
                    .disabled(busy)
                    .overlay { if busy { ProgressView().tint(GRColor.accent) } }
                } else {
                    Text(item.status == .approved ? "In your feed" : "Dismissed")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textTertiary)
                }
            }
        }
    }
}

#if DEBUG
#Preview("Inbox (mock)") {
    AgentInboxView(model: AgentInboxViewModel(useMocks: true))
        .preferredColorScheme(.dark)
}

#Preview("Suggestion card") {
    ZStack {
        GRColor.canvas.ignoresSafeArea()
        AgentSuggestionCard(item: AgentBridgeMocks.pendingItems[2]).padding()
    }
    .preferredColorScheme(.dark)
}
#endif
