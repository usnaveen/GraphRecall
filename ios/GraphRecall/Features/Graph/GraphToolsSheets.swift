import SwiftUI

// MARK: - Suggest links

/// AI link suggestions (`POST /api/nodes/{id}/suggest-links`) with per-link approval.
struct LinkSuggestionsSheet: View {
    let node: GraphNode
    let model: GraphViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var suggestions: [LinkSuggestion] = []
    @State private var selected: Set<String> = []
    @State private var isLoading = true
    @State private var isApplying = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Concepts in your graph that “\(node.name)” could connect to. Nothing changes until you apply.")
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textSecondary)

                        if isLoading {
                            HStack(spacing: 10) {
                                ProgressView().tint(GRColor.accent)
                                Text("Finding links…")
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.textSecondary)
                            }
                            .frame(maxWidth: .infinity, minHeight: 120)
                        } else if let errorMessage {
                            GRBanner(systemImage: "exclamationmark.triangle.fill", title: "Couldn’t suggest links", subtitle: errorMessage, tone: .warning)
                        } else if suggestions.isEmpty {
                            GRBanner(systemImage: "checkmark.seal.fill", title: "No new links", subtitle: "This concept already looks well connected.", tone: .accent)
                        }

                        ForEach(suggestions) { suggestion in
                            Button {
                                if selected.contains(suggestion.id) {
                                    selected.remove(suggestion.id)
                                } else {
                                    selected.insert(suggestion.id)
                                }
                                GRHaptics.tap()
                            } label: {
                                suggestionRow(suggestion)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(20)
                }
            }
            .navigationTitle("Suggest links")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                        .foregroundStyle(GRColor.textSecondary)
                }
            }
            .safeAreaInset(edge: .bottom) {
                if !suggestions.isEmpty {
                    Button {
                        Task { await apply() }
                    } label: {
                        if isApplying {
                            ProgressView().tint(GRColor.canvas)
                        } else {
                            Label("Apply \(selected.count) link\(selected.count == 1 ? "" : "s")", systemImage: "link.badge.plus")
                        }
                    }
                    .buttonStyle(.grPrimary)
                    .disabled(selected.isEmpty || isApplying)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 12)
                    .background(GRColor.canvas.opacity(0.92))
                }
            }
        }
        .preferredColorScheme(.dark)
        .task { await load() }
    }

    private func suggestionRow(_ suggestion: LinkSuggestion) -> some View {
        HStack(alignment: .top, spacing: 12) {
            GRCheckbox(isOn: selected.contains(suggestion.id))
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline) {
                    Text(suggestion.targetName ?? model.nodesById[suggestion.targetId]?.name ?? suggestion.targetId)
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Spacer()
                    GRChip(
                        title: suggestion.relationshipType.replacingOccurrences(of: "_", with: " ").capitalized,
                        style: .tinted(.cyan),
                        compact: true
                    )
                }
                if let reason = suggestion.reason, !reason.isEmpty {
                    Text(reason)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let strength = suggestion.strength {
                    GRProgressBar(value: strength, tint: GRColor.accentCyan, height: 4)
                }
            }
        }
        .padding(14)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        if model.usingStub {
            let connected = Set(model.neighbors(of: node.id).map(\.node.id))
            suggestions = model.graph.nodes
                .filter { $0.id != node.id && !connected.contains($0.id) && $0.domain == node.domain }
                .prefix(3)
                .map { LinkSuggestion(targetId: $0.id, targetName: $0.name, relationshipType: "RELATED_TO", strength: 0.6, reason: "Demo suggestion — same domain as \(node.name).") }
            selected = Set(suggestions.map(\.id))
            return
        }
        do {
            suggestions = try await APIClient.shared.suggestLinks(nodeId: node.id)
            selected = Set(suggestions.map(\.id))
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "link suggestions")
        }
    }

    private func apply() async {
        let chosen = suggestions.filter { selected.contains($0.id) }
        guard !chosen.isEmpty else { return }
        if model.usingStub {
            model.showToast("Demo graph — links not saved")
            dismiss()
            return
        }
        isApplying = true
        defer { isApplying = false }
        do {
            try await APIClient.shared.applyLinks(nodeId: node.id, links: chosen)
            GRHaptics.success()
            await model.reload(selecting: node.id)
            model.showToast("Linked \(chosen.count) concept\(chosen.count == 1 ? "" : "s")")
            dismiss()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "links")
        }
    }
}

// MARK: - Merge

/// Folds the selected concept into another one (`POST /api/concepts/merge`).
struct MergeConceptSheet: View {
    let node: GraphNode
    let model: GraphViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var target: GraphNode?
    @State private var confirming = false
    @State private var isMerging = false
    @State private var errorMessage: String?

    private var candidates: [GraphNode] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return model.graph.nodes
            .filter { $0.id != node.id && (q.isEmpty || $0.name.lowercased().contains(q)) }
            .sorted { lhs, rhs in
                let l = lhs.domain == node.domain, r = rhs.domain == node.domain
                return l == r ? lhs.name < rhs.name : l
            }
            .prefix(40)
            .map { $0 }
    }

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                VStack(alignment: .leading, spacing: 12) {
                    Text("Merge “\(node.name)” into another concept. Its links move to the target and “\(node.name)” is removed.")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)

                    HStack(spacing: 8) {
                        Image(systemName: "magnifyingglass").foregroundStyle(GRColor.textTertiary)
                        TextField("Find target concept…", text: $query)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .foregroundStyle(GRColor.textPrimary)
                    }
                    .padding(12)
                    .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 14, style: .continuous))

                    if let errorMessage {
                        GRBanner(systemImage: "exclamationmark.triangle.fill", title: "Merge failed", subtitle: errorMessage, tone: .warning)
                    }

                    ScrollView {
                        LazyVStack(spacing: 8) {
                            ForEach(candidates) { candidate in
                                Button {
                                    target = candidate
                                    GRHaptics.tap()
                                } label: {
                                    HStack(spacing: 12) {
                                        GRCheckbox(isOn: target?.id == candidate.id)
                                        Circle()
                                            .fill(Color(hex: candidate.color ?? "") ?? GRColor.accent)
                                            .frame(width: 8, height: 8)
                                        VStack(alignment: .leading, spacing: 1) {
                                            Text(candidate.name)
                                                .font(GRType.headline)
                                                .foregroundStyle(GRColor.textPrimary)
                                            if let domain = candidate.domain {
                                                Text(domain)
                                                    .font(GRType.caption)
                                                    .foregroundStyle(GRColor.textTertiary)
                                            }
                                        }
                                        Spacer()
                                    }
                                    .padding(12)
                                    .grGlassEffect(in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }
                .padding(20)
            }
            .navigationTitle("Merge concept")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                        .foregroundStyle(GRColor.textSecondary)
                }
            }
            .safeAreaInset(edge: .bottom) {
                Button {
                    confirming = true
                } label: {
                    if isMerging {
                        ProgressView().tint(GRColor.danger)
                    } else {
                        Label(target.map { "Merge into \($0.name)" } ?? "Pick a target", systemImage: "arrow.triangle.merge")
                    }
                }
                .buttonStyle(.grDestructive)
                .disabled(target == nil || isMerging)
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
                .background(GRColor.canvas.opacity(0.92))
            }
            .confirmationDialog(
                "Merge “\(node.name)” into “\(target?.name ?? "")”?",
                isPresented: $confirming,
                titleVisibility: .visible
            ) {
                Button("Merge", role: .destructive) {
                    Task { await merge() }
                }
            } message: {
                Text("“\(node.name)” will be removed. This can’t be undone.")
            }
        }
        .preferredColorScheme(.dark)
    }

    private func merge() async {
        guard let target else { return }
        if model.usingStub {
            model.showToast("Demo graph — merge skipped")
            dismiss()
            return
        }
        isMerging = true
        defer { isMerging = false }
        do {
            try await APIClient.shared.mergeConcepts(sourceIds: [node.id], into: target.id)
            GRHaptics.success()
            await model.reload(selecting: target.id)
            model.showToast("Merged into \(target.name)")
            dismiss()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "merge")
        }
    }
}
