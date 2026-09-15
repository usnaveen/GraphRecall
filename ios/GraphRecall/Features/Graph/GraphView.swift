import SwiftUI

struct GraphView: View {
    @State private var model = GraphViewModel()
    @Environment(AppRouter.self) private var router
    @FocusState private var searchFocused: Bool
    @State private var canvasHeight: CGFloat = 0
    @State private var panelHeight: CGFloat = 0

    /// Mastery colour mode legend — matches `MASTERY_COLORS` in the 3D scene.
    static let masteryLegend: [(String, Color)] = [
        ("Not reviewed", Color(hex: "#6B7280") ?? .gray),
        ("Weak", Color(hex: "#F87171") ?? .red),
        ("Learning", Color(hex: "#F59E0B") ?? .orange),
        ("Strong", Color(hex: "#34D399") ?? .green),
    ]

    var body: some View {
        @Bindable var bindable = model

        VStack(spacing: 10) {
            header
            if !isFocusLayout {
                searchBar(query: $bindable.searchQuery)
                if showsResults {
                    searchResultsCard
                        .padding(.horizontal, 20)
                } else {
                    filterChips
                }
            }
            canvasArea
        }
        .padding(.bottom, GRLayout.dockClearance)
        .background(GRColor.canvas.ignoresSafeArea())
        .animation(.easeInOut(duration: 0.2), value: showsResults)
        .animation(.snappy(duration: 0.3), value: isFocusLayout)
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
                    case .mergePicker: MergeTargetsSheet(node: node, model: model)
                    }
                }
            }
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        .sheet(item: $bindable.createDraft, onDismiss: { model.createSheetDismissed() }) { draft in
            CreateConceptSheet(draft: draft, model: model)
                .presentationDetents([.large])
        }
        .sheet(item: $bindable.quizTopic) { quiz in
            ScrollView {
                GraphQuizSheet(topic: quiz.topic, isDemo: model.usingStub) {
                    model.quizTopic = nil
                }
                .padding(16)
            }
            .background(GRColor.canvas.ignoresSafeArea())
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
            .preferredColorScheme(.dark)
        }
    }

    private var showsResults: Bool {
        searchFocused && !trimmedQuery.isEmpty
    }

    private var trimmedQuery: String {
        model.searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// While the full card (or notes / sources / quiz) is open, search and filters step aside so the
    /// graph keeps as much room as possible above the card.
    private var isFocusLayout: Bool {
        model.selectedNodeId != nil && !model.mergeMode && (model.cardExpanded || model.activeSheet != nil)
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
            TextField("Search concepts to quiz…", text: query)
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
                Button {
                    searchFocused = false
                    model.quizTopic = GraphViewModel.QuizTopic(topic: trimmedQuery)
                    GRHaptics.tap()
                } label: {
                    Label("Quiz me on “\(trimmedQuery)”", systemImage: "target")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.accent)
                        .lineLimit(1)
                        .padding(.vertical, 8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                if model.searchResults.isEmpty {
                    HStack {
                        Text(model.isSearching ? "Searching…" : "No exact match found.")
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textTertiary)
                        Spacer()
                        if !model.isSearching {
                            Button("Create this node") {
                                searchFocused = false
                                model.openCreate(name: trimmedQuery)
                            }
                            .font(GRType.caption.weight(.semibold))
                            .foregroundStyle(GRColor.accent)
                        }
                    }
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
                            if let community = model.community(containing: result.id), let title = community.title ?? community.label {
                                Text(title)
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.textTertiary)
                                    .lineLimit(1)
                            } else if let domain = result.domain {
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

    private var showsCanvasChrome: Bool {
        model.selectedNodeId == nil && model.activeSheet == nil && !model.mergeMode
    }

    private var hasBottomPanel: Bool {
        model.mergeMode || model.selectedNode != nil
    }

    /// Share of the canvas the bottom card covers, so the scene centres the focus above it.
    private var bottomInset: Double {
        guard hasBottomPanel, canvasHeight > 1 else { return 0 }
        return Double(min(0.9, (panelHeight + 10) / canvasHeight))
    }

    private var canvasArea: some View {
        ZStack(alignment: .bottom) {
            Graph3DWebView(
                graph: model.graph,
                graphVersion: model.graphVersion,
                state: model.sceneState,
                insetBottom: bottomInset,
                resetCameraToken: model.resetCameraToken,
                onEvent: handle
            )
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).stroke(GRColor.stroke, lineWidth: 1))
            .overlay(alignment: .topLeading) {
                controlsOverlay.padding(10)
            }
            .overlay(alignment: .topTrailing) {
                if model.usingStub { demoBadge.padding(10) }
            }
            .overlay(alignment: .bottomTrailing) {
                if showsCanvasChrome { canvasTools.padding(10) }
            }
            .overlay(alignment: .bottomLeading) {
                if showsCanvasChrome && model.colorMode == .mastery { masteryLegendView.padding(10) }
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
                bottomPanel
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { panelHeight = $0 }
            }
            .padding(.horizontal, 10)
            .padding(.bottom, 10)
            .animation(.easeInOut(duration: 0.22), value: model.selectedNodeId)
            .animation(.easeInOut(duration: 0.22), value: model.toast)
            .animation(.easeInOut(duration: 0.22), value: model.activeSheet?.id)
            .animation(.easeInOut(duration: 0.22), value: model.mergeMode)
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { canvasHeight = $0 }
        .padding(.horizontal, 16)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    @ViewBuilder
    private var bottomPanel: some View {
        if model.mergeMode {
            GraphMergeBar(model: model)
                .transition(.move(edge: .bottom).combined(with: .opacity))
        } else if let sheet = model.activeSheet, let node = model.selectedNode {
            ViewThatFits(in: .vertical) {
                sheetContent(sheet, node: node)
                ScrollView { sheetContent(sheet, node: node) }
                    .scrollIndicators(.hidden)
            }
            .frame(maxHeight: max(200, canvasHeight * 0.62))
            .transition(.move(edge: .bottom).combined(with: .opacity))
        } else if let node = model.selectedNode {
            GraphInspectorPanel(node: node, model: model, maxExpandedHeight: max(220, canvasHeight * 0.58)) {
                router.ask("Explain \(node.name) and how it connects to what I already know.", topic: node.name)
            }
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }

    private func handle(_ event: Graph3DEvent) {
        switch event {
        case .select(let id):
            withAnimation(.easeInOut(duration: 0.22)) { model.select(nodeId: id) }
            if id != nil { GRHaptics.tap() }
        case .mergeToggle(let id):
            model.toggleMergeTarget(id)
            GRHaptics.tap()
        case .createAt(let point):
            GRHaptics.tap()
            model.openCreate(position: point)
        case .layout(let running):
            model.isLayingOut = running
        }
    }

    private var controlsOverlay: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                GRIconButton(
                    systemImage: "slider.horizontal.3",
                    tint: model.showControls ? GRColor.accent : GRColor.textSecondary,
                    size: 36,
                    accessibilityLabel: model.showControls ? "Hide graph controls" : "Show graph controls"
                ) {
                    withAnimation(.easeInOut(duration: 0.2)) { model.showControls.toggle() }
                }
                GRIconButton(
                    systemImage: "scope",
                    tint: GRColor.textSecondary,
                    size: 36,
                    accessibilityLabel: "Fit graph to screen"
                ) {
                    model.resetCamera()
                }
                if model.isLayingOut && !model.isLoading {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.mini).tint(GRColor.accent)
                        Text("Laying out…")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textSecondary)
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .grGlassEffect(in: Capsule())
                }
            }
            if model.showControls {
                GraphControlsPanel(model: model)
                    .transition(.opacity.combined(with: .scale(scale: 0.96, anchor: .topLeading)))
            } else {
                // The key to the graph: which colour means which kind of connection.
                if model.selectedNodeId != nil { focusPill }
                relationshipLegend
            }
        }
    }

    /// Shown while a concept is selected — the scene is flat then, and this is the way back out.
    private var focusPill: some View {
        HStack(spacing: 6) {
            Image(systemName: "square.on.square.dashed")
                .font(.system(size: 11, weight: .bold))
            Text("2D focus")
                .font(GRType.micro.weight(.bold))
            Button {
                withAnimation(.easeInOut(duration: 0.22)) { model.select(nodeId: nil) }
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 9, weight: .bold))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Back to the 3D overview")
        }
        .foregroundStyle(GRColor.accent)
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .grGlassEffect(in: Capsule())
        .fixedSize()
    }

    /// Two columns of swatches, like the legend this screen used to carry — it names the link
    /// colours so the edges themselves stay clean.
    @ViewBuilder
    private var relationshipLegend: some View {
        let types = model.relationshipTypesInView
        if !types.isEmpty {
            let rows = stride(from: 0, to: types.count, by: 2).map { start in
                Array(types[start..<min(start + 2, types.count)])
            }
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 5) {
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    GridRow {
                        ForEach(row, id: \.self) { type in
                            HStack(spacing: 5) {
                                Capsule()
                                    .fill(GraphRelationshipStyle.color(type))
                                    .frame(width: 12, height: 3)
                                Text(GraphRelationshipStyle.label(type))
                                    .font(GRType.micro)
                                    .foregroundStyle(GRColor.textSecondary)
                                    .lineLimit(1)
                            }
                        }
                    }
                }
            }
            .fixedSize()
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .grGlassEffect(in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .accessibilityLabel("Connection colours")
        }
    }

    private var demoBadge: some View {
        Text("Demo graph")
            .font(GRType.micro)
            .foregroundStyle(GRColor.accent)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(GRColor.accentSoft, in: Capsule())
            .overlay(Capsule().stroke(GRColor.accentLine, lineWidth: 1))
    }

    private var canvasTools: some View {
        VStack(spacing: 4) {
            GRIconButton(
                systemImage: "target",
                style: .plain,
                tint: model.filter == .weak ? GRColor.accent : GRColor.textSecondary,
                size: 36,
                accessibilityLabel: "Weak-spot lens"
            ) {
                model.filter = model.filter == .weak ? .all : .weak
            }

            GRIconButton(systemImage: "plus", style: .accent, size: 36, accessibilityLabel: "Create concept") {
                model.openCreate()
            }
        }
        .padding(4)
        .grGlassEffect(in: Capsule())
    }

    private var masteryLegendView: some View {
        Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 5) {
            ForEach(0..<2, id: \.self) { row in
                GridRow {
                    ForEach(Self.masteryLegend[(row * 2)..<(row * 2 + 2)], id: \.0) { label, color in
                        HStack(spacing: 5) {
                            Circle().fill(color).frame(width: 7, height: 7)
                            Text(label)
                                .font(GRType.micro)
                                .foregroundStyle(GRColor.textSecondary)
                                .lineLimit(1)
                        }
                    }
                }
            }
        }
        .fixedSize()
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 14, style: .continuous))
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
