import SwiftUI

struct GraphView: View {
    @State private var model = GraphViewModel()
    @Environment(AppRouter.self) private var router
    @FocusState private var searchFocused: Bool

    static let legend: [(String, Color)] = [
        ("Prerequisite", GRColor.accentCyan),
        ("Builds on", GRColor.amber),
        ("Part of", Color(hex: "#EC4899") ?? GRColor.coral),
    ]

    var body: some View {
        @Bindable var bindable = model

        VStack(spacing: 10) {
            header
            searchBar(query: $bindable.searchQuery)
            if showsResults {
                searchResultsCard
                    .padding(.horizontal, 20)
            } else {
                filterChips
            }
            canvasArea
        }
        .padding(.bottom, GRLayout.dockClearance)
        .background(GRColor.canvas.ignoresSafeArea())
        .animation(.easeInOut(duration: 0.2), value: showsResults)
        .task {
            await model.load()
            applyPendingFocus()
        }
        .onChange(of: router.pendingGraphFocus) { _, _ in applyPendingFocus() }
        .onChange(of: model.searchQuery) { _, _ in model.updateSearch() }
        .sheet(item: $bindable.detailNode) { node in
            ConceptDetailView(node: node, graph: model)
                .environment(router)
        }
        .sheet(item: $bindable.toolSheet) { sheet in
            Group {
                if let node = model.selectedNode {
                    switch sheet {
                    case .suggestLinks: LinkSuggestionsSheet(node: node, model: model)
                    case .merge: MergeConceptSheet(node: node, model: model)
                    }
                }
            }
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
    }

    private var showsResults: Bool {
        searchFocused && !model.searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func applyPendingFocus() {
        guard let target = router.pendingGraphFocus, !model.graph.nodes.isEmpty else { return }
        router.pendingGraphFocus = nil
        if !model.focus(target) {
            model.showToast("“\(target)” isn’t in your graph yet")
        }
    }

    // MARK: - Header / search

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            GRScreenHeader(
                title: "Graph",
                subtitle: model.usingStub ? "Demo graph · API unreachable" : model.statsLabel
            )
            GRIconButton(systemImage: "arrow.clockwise", accessibilityLabel: "Reload graph") {
                Task { await model.load() }
            }
            .padding(.trailing, 20)
            .padding(.top, 14)
        }
    }

    private func searchBar(query: Binding<String>) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(GRColor.textTertiary)
            TextField("Search concepts…", text: query)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .foregroundStyle(GRColor.textPrimary)
                .focused($searchFocused)
                .submitLabel(.search)
                .onSubmit {
                    if let first = model.searchResults.first { pick(first) }
                }
            if model.isSearching {
                ProgressView().controlSize(.small).tint(GRColor.accent)
            }
            if !query.wrappedValue.isEmpty {
                Button {
                    query.wrappedValue = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(GRColor.textTertiary)
                }
                .accessibilityLabel("Clear search")
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .grGlassEffect(.interactive, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .padding(.horizontal, 20)
    }

    private var searchResultsCard: some View {
        GlassCard(cornerRadius: 18) {
            VStack(alignment: .leading, spacing: 4) {
                if model.searchResults.isEmpty {
                    Text(model.isSearching ? "Searching…" : "No concepts match")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textTertiary)
                        .padding(.vertical, 6)
                }
                ForEach(model.searchResults.prefix(6)) { result in
                    Button {
                        pick(result)
                    } label: {
                        HStack(spacing: 10) {
                            Circle()
                                .fill(Color(hex: result.color ?? "") ?? GRColor.accent)
                                .frame(width: 9, height: 9)
                            Text(result.name)
                                .font(GRType.headline)
                                .foregroundStyle(GRColor.textPrimary)
                                .lineLimit(1)
                            Spacer()
                            if let domain = result.domain {
                                Text(domain)
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.textTertiary)
                                    .lineLimit(1)
                            }
                        }
                        .padding(.vertical, 8)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func pick(_ result: GraphSearchResult) {
        model.searchQuery = ""
        searchFocused = false
        if !model.focus(result.id) {
            model.focus(result.name)
        }
        GRHaptics.tap()
    }

    private var filterChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                GRChip(title: "All", style: model.filter == .all ? .selected : .plain) {
                    model.filter = .all
                }
                GRChip(
                    title: "Weak < 40% · \(model.weakNodeIds.count)",
                    systemImage: "target",
                    style: model.filter == .weak ? .selected : .tinted(.accent)
                ) {
                    model.filter = model.filter == .weak ? .all : .weak
                    GRHaptics.tap()
                }
                ForEach(model.domains, id: \.self) { domain in
                    GRChip(title: domain, style: model.filter == .domain(domain) ? .selected : .plain) {
                        model.filter = model.filter == .domain(domain) ? .all : .domain(domain)
                        GRHaptics.tap()
                    }
                }
            }
            .padding(.horizontal, 20)
        }
    }

    // MARK: - Canvas

    private var canvasArea: some View {
        ZStack(alignment: .bottom) {
            GraphForceWebView(
                graph: model.graph,
                highlightIds: model.highlightSet,
                isDemo: model.usingStub,
                focusIds: model.focusCommunityIds,
                selectedId: model.selectedNodeId,
                onSelect: { id in
                    withAnimation(.easeInOut(duration: 0.22)) { model.select(nodeId: id) }
                },
                onCommunitiesRecompute: {
                    Task { await model.recomputeCommunities() }
                }
            )
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).stroke(GRColor.stroke, lineWidth: 1))
            // Top of the canvas belongs to the WebView's own controls + demo badge.
            .overlay(alignment: .bottomTrailing) {
                if model.selectedNodeId == nil && model.activeSheet == nil { canvasTools.padding(10) }
            }
            .overlay(alignment: .bottomLeading) {
                if model.selectedNodeId == nil && model.activeSheet == nil { legend.padding(10) }
            }

            if model.isLoading {
                ProgressView()
                    .tint(GRColor.accent)
                    .padding(16)
                    .grGlassEffect(in: Capsule())
                    .frame(maxHeight: .infinity)
            }

            VStack(spacing: 8) {
                if let toast = model.toast {
                    GRToast(message: toast)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                if let sheet = model.activeSheet, let node = model.selectedNode {
                    sheetContent(sheet, node: node)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                } else if let node = model.selectedNode {
                    GraphInspectorPanel(node: node, model: model) {
                        router.ask("Explain \(node.name) and how it connects to what I already know.", topic: node.name)
                    }
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .padding(.horizontal, 10)
            .padding(.bottom, 10)
            .animation(.easeInOut(duration: 0.22), value: model.selectedNodeId)
            .animation(.easeInOut(duration: 0.22), value: model.toast)
            .animation(.easeInOut(duration: 0.22), value: model.activeSheet?.id)
        }
        .padding(.horizontal, 16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var canvasTools: some View {
        VStack(spacing: 4) {
            GRIconButton(
                systemImage: "square.3.layers.3d",
                style: .plain,
                tint: model.isolateCommunity ? GRColor.accent : GRColor.textSecondary,
                size: 36,
                accessibilityLabel: model.isolateCommunity ? "Show all communities" : "Isolate community"
            ) {
                model.toggleCommunityFocus()
            }
            .disabled(model.selectedNodeId == nil)
            .opacity(model.selectedNodeId == nil ? 0.45 : 1)

            GRIconButton(
                systemImage: "target",
                style: .plain,
                tint: model.filter == .weak ? GRColor.accent : GRColor.textSecondary,
                size: 36,
                accessibilityLabel: "Weak-spot lens"
            ) {
                model.filter = model.filter == .weak ? .all : .weak
            }

            GRIconButton(
                systemImage: "arrow.triangle.2.circlepath",
                style: .plain,
                tint: model.isRecomputingCommunities ? GRColor.accent : GRColor.textSecondary,
                size: 36,
                accessibilityLabel: "Recompute communities"
            ) {
                Task { await model.recomputeCommunities() }
            }
        }
        .padding(4)
        .grGlassEffect(in: Capsule())
    }

    private var legend: some View {
        HStack(spacing: 10) {
            ForEach(Self.legend, id: \.0) { label, color in
                HStack(spacing: 5) {
                    Circle().fill(color).frame(width: 7, height: 7)
                    Text(label)
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textSecondary)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
        .grGlassEffect(in: Capsule())
    }

    @ViewBuilder
    private func sheetContent(_ sheet: GraphViewModel.InspectorSheet, node: GraphNode) -> some View {
        switch sheet {
        case .notes:
            GraphNotePanel(
                conceptId: node.id,
                conceptName: node.name,
                isDemo: model.usingStub,
                onClose: { model.closeSheet() }
            )
        case .links:
            GraphLinksSheet(
                conceptName: node.name,
                isDemo: model.usingStub,
                onClose: { model.closeSheet() }
            )
        case .quiz:
            GraphQuizSheet(
                topic: node.name,
                isDemo: model.usingStub,
                onClose: { model.closeSheet() }
            )
        }
    }
}

#Preview {
    ZStack {
        GRColor.canvas.ignoresSafeArea()
        GraphView()
    }
    .environment(AppRouter())
    .preferredColorScheme(.dark)
}
