import SwiftUI

// MARK: - Graph Controls (web Controls.tsx)

/// Domain filter, relationship-weight threshold, community toggles and statistics.
struct GraphControlsPanel: View {
    @Bindable var model: GraphViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Graph Controls", systemImage: "line.3.horizontal.decrease")
                .font(GRType.caption.weight(.semibold))
                .foregroundStyle(GRColor.textSecondary)

            VStack(alignment: .leading, spacing: 5) {
                caption("Domain")
                Menu {
                    Button("All Domains") { model.filter = .all }
                    ForEach(model.domains.sorted(), id: \.self) { domain in
                        Button(domain) { model.filter = .domain(domain) }
                    }
                } label: {
                    HStack {
                        Text(model.selectedDomain ?? "All Domains")
                            .lineLimit(1)
                        Spacer(minLength: 4)
                        Image(systemName: "chevron.down")
                            .font(.caption2)
                            .foregroundStyle(GRColor.textTertiary)
                    }
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textPrimary)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(GRColor.stroke, lineWidth: 1))
                }
            }

            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    caption("Min Weight")
                    Spacer()
                    Text("\(Int((model.minRelationshipWeight * 100).rounded()))%")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textSecondary)
                }
                Slider(value: $model.minRelationshipWeight, in: 0...1, step: 0.05)
                    .tint(GRColor.accent)
                    .accessibilityLabel("Minimum relationship weight")
            }

            VStack(alignment: .leading, spacing: 5) {
                caption("Color by")
                HStack(spacing: 6) {
                    ForEach(GraphColorMode.allCases) { mode in
                        Button {
                            model.colorMode = mode
                            GRHaptics.tap()
                        } label: {
                            Text(mode.title).frame(maxWidth: .infinity)
                        }
                        .buttonStyle(ControlPillStyle(active: model.colorMode == mode))
                    }
                }
            }

            VStack(alignment: .leading, spacing: 5) {
                caption("Communities")
                Button {
                    Task { await model.recomputeCommunities() }
                } label: {
                    Group {
                        if model.isRecomputingCommunities {
                            ProgressView().controlSize(.mini).tint(GRColor.accent)
                        } else {
                            Label("Recompute communities", systemImage: "arrow.triangle.2.circlepath")
                        }
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(ControlPillStyle(active: false))
                .disabled(model.isRecomputingCommunities)
                if model.communityLevelCount > 1 {
                    Text("\(model.communityLevelCount) levels detected")
                        .font(.system(size: 9, weight: .medium, design: .rounded))
                        .foregroundStyle(GRColor.textTertiary)
                }
            }

            Divider().overlay(GRColor.stroke)

            VStack(alignment: .leading, spacing: 4) {
                Label("Statistics", systemImage: "chart.bar")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                HStack {
                    Text("Nodes: \(model.visibleNodeCount) / \(model.graph.nodes.count)")
                    Spacer(minLength: 6)
                    Text("Links: \(model.visibleLinkCount) / \(model.graph.edges.count)")
                }
                .font(GRType.micro)
                .foregroundStyle(GRColor.textSecondary)
            }

            Text("Drag to orbit · pinch to zoom · tap a concept to focus it · double-tap space to fly to the nearest one · long-press space to add one")
                .font(.system(size: 9, weight: .medium, design: .rounded))
                .foregroundStyle(GRColor.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(width: 236)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(GRColor.stroke, lineWidth: 1))
    }

    private func caption(_ text: String) -> some View {
        Text(text.uppercased())
            .font(.system(size: 9, weight: .semibold, design: .rounded))
            .tracking(0.8)
            .foregroundStyle(GRColor.textTertiary)
    }
}

private struct ControlPillStyle: ButtonStyle {
    let active: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(GRType.micro)
            .foregroundStyle(active ? GRColor.accent : GRColor.textSecondary)
            .padding(.vertical, 6)
            .background(
                (active ? GRColor.accentSoft : GRColor.fillSubtle).opacity(configuration.isPressed ? 0.6 : 1),
                in: RoundedRectangle(cornerRadius: 9, style: .continuous)
            )
    }
}

// MARK: - Merge mode bar

/// Shown while the graph is in merge mode: tapped concepts fold into the selected one.
struct GraphMergeBar: View {
    let model: GraphViewModel

    static let orange = Color(red: 0.976, green: 0.451, blue: 0.086) // #F97316, web merge colour

    @State private var confirming = false

    private var count: Int { model.mergeTargetIds.count }
    private var sourceName: String { model.selectedNode?.name ?? "this concept" }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "arrow.triangle.merge")
                    .foregroundStyle(Self.orange)
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Merge mode")
                        .font(GRType.headline)
                        .foregroundStyle(Self.orange)
                    Text("Tap concepts in the graph to fold into “\(sourceName)”. \(count) selected.")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 4)
                GRIconButton(systemImage: "list.bullet", style: .plain, size: 32, accessibilityLabel: "Pick concepts from a list") {
                    model.toolSheet = .mergePicker
                }
            }

            HStack(spacing: 8) {
                Button("Cancel") { model.exitMergeMode() }
                    .grButton(.secondary, compact: true)

                Button {
                    confirming = true
                } label: {
                    Group {
                        if model.isMerging {
                            ProgressView().tint(.white)
                        } else {
                            Label("Merge \(count) → 1", systemImage: "arrow.triangle.merge")
                        }
                    }
                    .font(GRType.caption.weight(.semibold))
                    .foregroundStyle(.white)
                }
                .buttonStyle(.glassProminent)
                .buttonBorderShape(.capsule)
                .buttonSizing(.flexible)
                .tint(Self.orange)
                .disabled(count == 0 || model.isMerging)
            }
        }
        .padding(16)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).stroke(Self.orange.opacity(0.3), lineWidth: 1))
        .confirmationDialog(
            "Merge \(count) concept\(count == 1 ? "" : "s") into “\(sourceName)”?",
            isPresented: $confirming,
            titleVisibility: .visible
        ) {
            Button("Merge", role: .destructive) {
                Task {
                    if await model.performMerge() { GRHaptics.success() }
                }
            }
        } message: {
            Text("Their links move to “\(sourceName)” and they are removed. This can’t be undone.")
        }
    }
}

// MARK: - Create concept (web Create Concept modal)

struct CreateConceptSheet: View {
    let draft: GraphViewModel.CreateConceptDraft
    let model: GraphViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var description = ""
    @State private var domain = "General"
    @State private var parentQuery = ""
    @State private var parent: GraphNode?
    @State private var isCreating = false
    @State private var errorMessage: String?
    @FocusState private var nameFocused: Bool

    private var trimmedName: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }

    private var parentMatches: [GraphNode] {
        let q = parentQuery.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard parent == nil, !q.isEmpty else { return [] }
        return model.graph.nodes.filter { $0.name.lowercased().contains(q) }.prefix(5).map { $0 }
    }

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        if draft.position != nil {
                            Label("Placed where you long-pressed in the graph", systemImage: "scope")
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textSecondary)
                        }

                        TextField("Concept name", text: $name)
                            .focused($nameFocused)
                            .submitLabel(.next)
                            .modifier(CreateFieldStyle())

                        TextField("Description (optional)", text: $description, axis: .vertical)
                            .lineLimit(3...6)
                            .modifier(CreateFieldStyle())

                        Menu {
                            ForEach(model.creatableDomains, id: \.self) { option in
                                Button(option) { domain = option }
                            }
                        } label: {
                            HStack {
                                Text(domain)
                                    .foregroundStyle(GRColor.textPrimary)
                                Spacer()
                                Image(systemName: "chevron.down")
                                    .foregroundStyle(GRColor.textTertiary)
                            }
                            .modifier(CreateFieldStyle())
                        }
                        .accessibilityLabel("Domain, \(domain)")

                        parentPicker

                        if let errorMessage {
                            GRBanner(systemImage: "exclamationmark.triangle.fill", title: "Couldn’t create concept", subtitle: errorMessage, tone: .warning)
                        }
                    }
                    .padding(20)
                }
            }
            .navigationTitle("Create Concept")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                        .foregroundStyle(GRColor.textSecondary)
                }
            }
            .safeAreaInset(edge: .bottom) {
                Button {
                    Task { await create() }
                } label: {
                    if isCreating {
                        ProgressView().tint(GRColor.canvas)
                    } else {
                        Label("Create", systemImage: "plus")
                    }
                }
                .grButton(.primary)
                .disabled(trimmedName.isEmpty || isCreating)
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
                .background(GRColor.canvas.opacity(0.92))
            }
        }
        .preferredColorScheme(.dark)
        .onAppear {
            name = draft.name
            nameFocused = draft.name.isEmpty
        }
    }

    @ViewBuilder
    private var parentPicker: some View {
        if let parent {
            HStack(spacing: 10) {
                Circle()
                    .fill(Color(hex: parent.color ?? "") ?? GRColor.accent)
                    .frame(width: 8, height: 8)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Subtopic of")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    Text(parent.name)
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                }
                Spacer()
                Button {
                    self.parent = nil
                    parentQuery = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(GRColor.textTertiary)
                }
                .accessibilityLabel("Remove parent concept")
            }
            .modifier(CreateFieldStyle())
        } else {
            VStack(alignment: .leading, spacing: 6) {
                TextField("Parent concept (optional)", text: $parentQuery)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .modifier(CreateFieldStyle())
                ForEach(parentMatches) { match in
                    Button {
                        parent = match
                        parentQuery = match.name
                        GRHaptics.tap()
                    } label: {
                        HStack {
                            Text(match.name)
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textPrimary)
                            if let matchDomain = match.domain {
                                Text(matchDomain)
                                    .font(GRType.micro)
                                    .foregroundStyle(GRColor.textTertiary)
                            }
                            Spacer()
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func create() async {
        guard !trimmedName.isEmpty else { return }
        isCreating = true
        defer { isCreating = false }
        do {
            try await model.createConcept(
                name: trimmedName,
                description: description,
                domain: domain,
                parentId: parent?.id,
                position: draft.position
            )
            GRHaptics.success()
            dismiss()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "concept")
        }
    }
}

private struct CreateFieldStyle: ViewModifier {
    func body(content: Content) -> some View {
        content
            .font(GRType.body)
            .foregroundStyle(GRColor.textPrimary)
            .padding(12)
            .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(GRColor.stroke, lineWidth: 1))
    }
}
