import SwiftUI

struct GraphView: View {
    @State private var model = GraphViewModel()

    var body: some View {
        VStack(spacing: 0) {
            header
            searchBar
            ZStack(alignment: .bottom) {
                GraphForceWebView(
                    graph: model.graph,
                    highlightIds: highlightSet,
                    isDemo: model.usingStub,
                    focusIds: model.focusCommunityIds,
                    selectedId: model.selectedNodeId,
                    onSelect: { id in model.select(nodeId: id) },
                    onCommunitiesRecompute: {
                        Task { await model.recomputeCommunities() }
                    }
                )
                .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                .padding(.horizontal, 16)
                .padding(.top, 8)

                if model.isLoading {
                    ProgressView()
                        .tint(GRColor.accent)
                        .padding(16)
                        .grGlassEffect(in: Capsule())
                }

                VStack(spacing: 8) {
                    if let notice = model.communityRecomputeNotice {
                        Text(notice)
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textSecondary)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .grGlassEffect(in: Capsule())
                            .transition(.opacity)
                    }

                    if let sheet = model.activeSheet, let node = model.selectedNode {
                        sheetContent(sheet, node: node)
                            .padding(.horizontal, 16)
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    } else if let node = model.selectedNode {
                        GraphInspectorPanel(
                            node: node,
                            edges: model.connectedEdges,
                            communities: model.graph.communities,
                            nodesById: model.nodesById,
                            isRecomputing: model.isRecomputingCommunities,
                            onClose: { model.select(nodeId: nil) },
                            onSelectNode: { model.select(nodeId: $0) },
                            onFocusCommunity: { model.toggleCommunityFocus() },
                            isolateCommunity: model.isolateCommunity,
                            onQuiz: { model.openQuiz() },
                            onNotes: { model.openNotes() },
                            onLinks: { model.openLinks() }
                        )
                        .padding(.horizontal, 16)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                }
                .padding(.bottom, 12)
                .animation(.easeInOut(duration: 0.22), value: model.selectedNodeId)
                .animation(.easeInOut(duration: 0.22), value: model.communityRecomputeNotice)
                .animation(.easeInOut(duration: 0.22), value: model.activeSheet?.id)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .padding(.bottom, GRLayout.dockClearance)
        .task { await model.load() }
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

    private var highlightSet: Set<String> {
        if !model.focusCommunityIds.isEmpty {
            return model.focusCommunityIds
        }
        let q = model.searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        if !q.isEmpty {
            return Set(model.filteredNodes.map(\.id))
        }
        if let id = model.selectedNodeId { return [id] }
        return []
    }

    private var header: some View {
        ZStack(alignment: .trailing) {
            GRScreenHeader(
                title: "Graph",
                subtitle: model.usingStub ? "Demo graph · API unreachable" : model.statsLabel
            )
            Button {
                Task { await model.load() }
            } label: {
                Image(systemName: "arrow.clockwise")
                    .foregroundStyle(GRColor.accent)
                    .padding(10)
                    .grGlassEffect(.interactive, in: Circle())
            }
            .padding(.trailing, 20)
            .padding(.top, 10)
        }
    }

    private var searchBar: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(GRColor.textTertiary)
            TextField("Find concept…", text: $model.searchQuery)
                .textInputAutocapitalization(.never)
                .disableAutocorrection(true)
                .foregroundStyle(GRColor.textPrimary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .grGlassEffect(.interactive, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .padding(.horizontal, 20)
    }
}

#Preview {
    ZStack {
        GRColor.canvas.ignoresSafeArea()
        GraphView()
    }
    .preferredColorScheme(.dark)
}
