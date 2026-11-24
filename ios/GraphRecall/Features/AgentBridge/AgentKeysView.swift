import Observation
import SwiftUI
import UIKit

@MainActor
@Observable
final class AgentKeysViewModel {
    var keys: [AgentKey] = []
    var isLoading = false
    var errorMessage: String?
    /// Plaintext of a key just created. Shown once, cleared when the sheet closes; never persisted.
    var revealedSecret: CreatedAgentKey?
    var isCreating = false

    @ObservationIgnored private let useMocks: Bool

    init(useMocks: Bool = false) {
        self.useMocks = useMocks
        if useMocks { keys = AgentBridgeMocks.keys }
    }

    var activeKeys: [AgentKey] { keys.filter(\.isActive) }
    var inactiveKeys: [AgentKey] { keys.filter { !$0.isActive } }

    func load() async {
        guard !useMocks else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            keys = try await APIClient.shared.agentKeys()
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "agent keys")
        }
    }

    func create(name: String, scopes: Set<AgentScope>, expiresInDays: Int) async {
        guard !scopes.isEmpty else {
            errorMessage = "Pick at least one permission."
            return
        }
        isCreating = true
        defer { isCreating = false }
        let ordered = AgentScope.allCases.filter { scopes.contains($0) }
        if useMocks {
            let key = AgentKey(id: UUID().uuidString, name: name, keyPrefix: "grk_mock1234",
                               scopes: ordered.map(\.rawValue))
            keys.insert(key, at: 0)
            revealedSecret = CreatedAgentKey(key: key, apiKey: "grk_mock1234_preview-secret-not-real", warning: nil)
            return
        }
        do {
            let created = try await APIClient.shared.createAgentKey(name: name, scopes: ordered, expiresInDays: expiresInDays)
            revealedSecret = created
            errorMessage = nil
            await load()
        } catch APIError.http(409, _) {
            errorMessage = "You already have 5 active keys. Revoke one first."
        } catch {
            errorMessage = APIError.userFacing(error, resource: "agent keys")
        }
    }

    func revoke(_ key: AgentKey) async {
        if useMocks {
            keys.removeAll { $0.id == key.id }
            return
        }
        do {
            try await APIClient.shared.revokeAgentKey(id: key.id)
            await load()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "agent keys")
        }
    }
}

/// Settings → Agent → Agent keys. Keys are scoped, per-user, hashed at rest on the server,
/// and the plaintext is shown exactly once after creation.
struct AgentKeysView: View {
    @State private var model: AgentKeysViewModel
    @State private var showCreate = false
    @State private var pendingRevoke: AgentKey?

    init(model: AgentKeysViewModel = AgentKeysViewModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        ZStack {
            GRColor.canvas.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text("An agent key lets an outside agent (for example Grok Bot) connect to GraphRecall over MCP. It only sees your data, only does what you allow, and anything it suggests waits for your approval.")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)

                    if let error = model.errorMessage {
                        GRBanner(systemImage: "exclamationmark.triangle.fill", title: "Agent keys", subtitle: error, tone: .warning)
                    }

                    if model.isLoading && model.keys.isEmpty {
                        ProgressView().tint(GRColor.accent).frame(maxWidth: .infinity).padding(.top, 30)
                    }

                    ForEach(model.activeKeys) { key in
                        AgentKeyRow(key: key) { pendingRevoke = key }
                    }

                    if !model.inactiveKeys.isEmpty {
                        Text("REVOKED OR EXPIRED")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                            .padding(.top, 8)
                        ForEach(model.inactiveKeys) { key in
                            AgentKeyRow(key: key, onRevoke: nil)
                        }
                    }

                    Button {
                        showCreate = true
                    } label: {
                        Label("New agent key", systemImage: "plus")
                    }
                    .buttonStyle(GRButtonStyle(kind: .primary))
                    .disabled(model.activeKeys.count >= 5)
                    .padding(.top, 6)
                }
                .padding(20)
            }
            .refreshable { await model.load() }
        }
        .navigationTitle("Agent keys")
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load() }
        .sheet(isPresented: $showCreate) {
            AgentKeyCreateSheet(model: model)
                .presentationDetents([.large])
        }
        .confirmationDialog(
            "Revoke \(pendingRevoke?.name ?? "this key")?",
            isPresented: Binding(get: { pendingRevoke != nil }, set: { if !$0 { pendingRevoke = nil } }),
            titleVisibility: .visible
        ) {
            Button("Revoke", role: .destructive) {
                if let key = pendingRevoke { Task { await model.revoke(key) } }
                pendingRevoke = nil
            }
        } message: {
            Text("The agent using it loses access immediately.")
        }
    }
}

struct AgentKeyRow: View {
    let key: AgentKey
    var onRevoke: (() -> Void)?

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(verbatim: key.name)
                        .font(GRType.headline)
                        .foregroundStyle(key.isActive ? GRColor.textPrimary : GRColor.textTertiary)
                    Spacer()
                    Text(verbatim: key.keyPrefix + "_…")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(GRColor.textTertiary)
                }
                GRFlowLayout {
                    ForEach(key.scopes, id: \.self) { scope in
                        GRChip(title: AgentScope(rawValue: scope)?.label ?? scope, style: .plain, compact: true)
                    }
                }
                HStack(spacing: 12) {
                    if let used = key.lastUsed {
                        Text("Used \(used, format: .relative(presentation: .named))")
                    } else {
                        Text("Never used")
                    }
                    if key.isRevoked {
                        Text("Revoked")
                    } else if let exp = key.expiry {
                        Text(key.isExpired ? "Expired" : "Expires \(exp, format: .dateTime.day().month(.abbreviated).year())")
                    }
                }
                .font(GRType.caption)
                .foregroundStyle(GRColor.textTertiary)

                if let onRevoke {
                    Button(role: .destructive, action: onRevoke) {
                        Label("Revoke", systemImage: "xmark.octagon")
                    }
                    .buttonStyle(GRButtonStyle(kind: .destructive, fullWidth: false, compact: true))
                }
            }
        }
    }
}

struct AgentKeyCreateSheet: View {
    let model: AgentKeysViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var name = "Grok Bot"
    @State private var scopes: Set<AgentScope> = Set(AgentScope.allCases)
    @State private var expiresInDays = 90
    @State private var copied = false

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        if let created = model.revealedSecret {
                            secretCard(created)
                        } else {
                            form
                        }
                    }
                    .padding(20)
                }
            }
            .navigationTitle(model.revealedSecret == nil ? "New agent key" : "Copy your key")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(model.revealedSecret == nil ? "Cancel" : "Done") { close() }
                }
            }
        }
        .interactiveDismissDisabled(model.revealedSecret != nil && !copied)
        .onDisappear { model.revealedSecret = nil }
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: 16) {
            TextField("Name", text: $name)
                .font(GRType.body)
                .padding(12)
                .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 12, style: .continuous))

            Text("PERMISSIONS")
                .font(GRType.micro)
                .foregroundStyle(GRColor.textTertiary)
            ForEach(AgentScope.allCases) { scope in
                Toggle(isOn: Binding(
                    get: { scopes.contains(scope) },
                    set: { on in if on { scopes.insert(scope) } else { scopes.remove(scope) } }
                )) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(scope.label).font(GRType.body).foregroundStyle(GRColor.textPrimary)
                        Text(scope.detail).font(GRType.caption).foregroundStyle(GRColor.textSecondary)
                    }
                }
                .tint(GRColor.accent)
            }

            Picker("Expires", selection: $expiresInDays) {
                Text("30 days").tag(30)
                Text("90 days").tag(90)
                Text("1 year").tag(365)
            }
            .pickerStyle(.segmented)

            if let error = model.errorMessage {
                Text(error).font(GRType.caption).foregroundStyle(GRColor.warning)
            }

            Button {
                Task {
                    await model.create(
                        name: name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "Agent" : name,
                        scopes: scopes,
                        expiresInDays: expiresInDays
                    )
                }
            } label: {
                if model.isCreating { ProgressView().tint(.white) } else { Text("Create key") }
            }
            .buttonStyle(GRButtonStyle(kind: .primary))
            .disabled(model.isCreating || scopes.isEmpty)
        }
    }

    private func secretCard(_ created: CreatedAgentKey) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            GRBanner(
                systemImage: "exclamationmark.shield.fill",
                title: "Copy this key now",
                subtitle: created.warning ?? "GraphRecall stores only a hash of it. You won\u{2019}t see it again.",
                tone: .warning
            )
            Text(verbatim: created.apiKey)
                .font(.system(.footnote, design: .monospaced))
                .foregroundStyle(GRColor.textPrimary)
                .textSelection(.enabled)
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .privacySensitive()
            Button {
                // Expire from the clipboard after 2 minutes; local-only so it never syncs via Handoff.
                UIPasteboard.general.setItems(
                    [[UIPasteboard.typeAutomatic: created.apiKey]],
                    options: [.localOnly: true, .expirationDate: Date().addingTimeInterval(120)]
                )
                copied = true
                GRHaptics.tap()
            } label: {
                Label(copied ? "Copied" : "Copy key", systemImage: copied ? "checkmark" : "doc.on.doc")
            }
            .buttonStyle(GRButtonStyle(kind: .primary))
            Text("Paste it into your agent\u{2019}s GraphRecall connector as a Bearer token. MCP endpoint: \(APIConfig.baseURL.absoluteString)/mcp/agent")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func close() {
        model.revealedSecret = nil
        dismiss()
    }
}

#if DEBUG
#Preview("Agent keys (mock)") {
    NavigationStack {
        AgentKeysView(model: AgentKeysViewModel(useMocks: true))
    }
    .preferredColorScheme(.dark)
}
#endif
