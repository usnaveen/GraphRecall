import Foundation
import Observation

@MainActor
@Observable
final class GraphViewModel {
    var graph = Graph3DResponse() {
        didSet { graphVersion &+= 1 }
    }
    /// Bumped on every graph replacement so the 3D page only re-runs its layout for new data.
    private(set) var graphVersion = 0
    var isLoading = false
    /// The 3D page is running its force layout.
    var isLayingOut = false
    var isRecomputingCommunities = false
    var errorMessage: String?
    var usingStub = false
    var selectedNodeId: String?
    var searchQuery: String = ""
    var isolateCommunity = false
    var activeSheet: InspectorSheet?
    var filter: GraphFilter = .all
    var searchResults: [GraphSearchResult] = []
    var isSearching = false
    /// Concept shown in the full-screen Concept detail sheet.
    var detailNode: GraphNode?
    var toolSheet: ToolSheet?
    var toast: String?

    // Graph Controls (web Controls.tsx)
    var showControls = false
    var colorMode: GraphColorMode = .domain
    var minRelationshipWeight = 0.0
    /// The selected-concept card shows everything instead of the compact summary.
    var cardExpanded = false
    var resetCameraToken = 0

    // Merge mode (web GraphScreen): the selected concept absorbs the concepts tapped in the graph.
    var mergeMode = false
    var mergeTargetIds: Set<String> = []
    var isMerging = false

    var createDraft: CreateConceptDraft?
    var quizTopic: QuizTopic?

    @ObservationIgnored private var searchTask: Task<Void, Never>?
    @ObservationIgnored private var toastTask: Task<Void, Never>?
    @ObservationIgnored private var loadGeneration = 0
    @ObservationIgnored private var pendingLinkSuggestionsId: String?

    enum InspectorSheet: String, Identifiable {
        case notes, links, quiz
        var id: String { rawValue }
    }

    enum ToolSheet: String, Identifiable {
        case suggestLinks, mergePicker
        var id: String { rawValue }
    }

    enum GraphFilter: Hashable {
        case all, weak, domain(String)
    }

    struct CreateConceptDraft: Identifiable {
        let id = UUID()
        var name: String
        var position: GraphPoint3D?
    }

    struct QuizTopic: Identifiable {
        let topic: String
        var id: String { topic }
    }

    static let weakThreshold = 0.4
    /// Concepts per `/api/graph3d` request; later pages load in the background like the web.
    static let pageSize = 1000

    var filteredNodes: [GraphNode] {
        let q = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return graph.nodes }
        return graph.nodes.filter {
            $0.name.lowercased().contains(q) || ($0.domain?.lowercased().contains(q) ?? false)
        }
    }

    var selectedNode: GraphNode? {
        guard let selectedNodeId else { return nil }
        return graph.nodes.first { $0.id == selectedNodeId }
    }

    var connectedEdges: [GraphEdge] {
        guard let selectedNodeId else { return [] }
        return graph.edges.filter { $0.source == selectedNodeId || $0.target == selectedNodeId }
            .sorted { ($0.strength ?? 0) > ($1.strength ?? 0) }
    }

    var nodesById: [String: GraphNode] {
        Dictionary(graph.nodes.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
    }

    var statsLabel: String {
        let comm = graph.communities.isEmpty ? "" : " · \(graph.communities.count) communities"
        return "\(graph.totalNodes) concepts · \(graph.totalEdges) links\(comm)"
    }

    /// Domains ordered by concept count — filter chips.
    var domains: [String] {
        var counts: [String: Int] = [:]
        for node in graph.nodes {
            guard let d = node.domain, !d.isEmpty else { continue }
            counts[d, default: 0] += 1
        }
        return counts.sorted { $0.value == $1.value ? $0.key < $1.key : $0.value > $1.value }.map(\.key)
    }

    /// Domains offered when creating a concept (web `availableDomains`).
    var creatableDomains: [String] {
        Array(Set(domains).union(["General"])).sorted()
    }

    var weakNodeIds: Set<String> {
        Set(graph.nodes.filter { ($0.masteryLevel ?? 0) < Self.weakThreshold }.map(\.id))
    }

    var selectedDomain: String? {
        if case .domain(let domain) = filter { return domain }
        return nil
    }

    // MARK: - Scene

    /// Members of the selected concept's community while "Isolate community" is on.
    var isolatedCommunityIds: Set<String>? {
        guard isolateCommunity, let selectedNodeId, let community = community(containing: selectedNodeId) else {
            return nil
        }
        return Set(community.entityIds)
    }

    /// Nodes drawn enlarged: search matches first, then the weak-spot lens.
    var highlightSet: Set<String> {
        if !searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return Set(filteredNodes.map(\.id))
        }
        return filter == .weak ? weakNodeIds : []
    }

    var sceneState: GraphSceneState {
        GraphSceneState(
            selectedId: selectedNodeId,
            highlightIds: highlightSet,
            visibleIds: isolatedCommunityIds,
            domain: selectedDomain,
            minWeight: minRelationshipWeight,
            colorMode: colorMode,
            mergeMode: mergeMode,
            mergeTargetIds: mergeTargetIds
        )
    }

    private func isVisible(_ node: GraphNode) -> Bool {
        if let ids = isolatedCommunityIds, !ids.contains(node.id) { return false }
        if let domain = selectedDomain, node.domain != domain { return false }
        return true
    }

    var visibleNodeCount: Int {
        graph.nodes.filter(isVisible).count
    }

    var visibleLinkCount: Int {
        let ids = Set(graph.nodes.filter(isVisible).map(\.id))
        return graph.edges.filter { edge in
            ids.contains(edge.source) && ids.contains(edge.target)
                && (minRelationshipWeight <= 0 || (edge.strength ?? 0.6) >= minRelationshipWeight)
        }.count
    }

    var communityLevelCount: Int {
        Set(graph.communities.compactMap(\.level)).count
    }

    // MARK: - Loading

    func load() async {
        loadGeneration &+= 1
        let generation = loadGeneration
        isLoading = true
        errorMessage = nil
        var hasFirstPage = false

        do {
            var merged = try await APIClient.shared.fetchGraph(limit: Self.pageSize, offset: 0)
            guard generation == loadGeneration else { return }
            apply(merged)
            hasFirstPage = true
            isLoading = false

            // Keep paging while full pages come back, re-laying out as the graph grows.
            var offset = Self.pageSize
            var lastPageCount = merged.nodes.count
            while lastPageCount == Self.pageSize {
                let page = try await APIClient.shared.fetchGraph(limit: Self.pageSize, offset: offset)
                guard generation == loadGeneration else { return }
                let combined = Self.combine(merged, page)
                guard combined.nodes.count > merged.nodes.count else { break }
                merged = combined
                apply(merged)
                offset += Self.pageSize
                lastPageCount = page.nodes.count
            }
        } catch {
            guard generation == loadGeneration else { return }
            isLoading = false
            // A failed background page keeps what is already on screen.
            guard !hasFirstPage else { return }
            errorMessage = Self.sanitizeError(error)
            graph = Self.stubGraph()
            usingStub = true
        }
    }

    private func apply(_ response: Graph3DResponse) {
        graph = response
        usingStub = false
        let ids = Set(response.nodes.map(\.id))
        if let selectedNodeId, !ids.contains(selectedNodeId) {
            self.selectedNodeId = nil
            exitMergeMode()
        }
        mergeTargetIds.formIntersection(ids)
    }

    private static func combine(_ current: Graph3DResponse, _ page: Graph3DResponse) -> Graph3DResponse {
        let nodeIds = Set(current.nodes.map(\.id))
        let edgeIds = Set(current.edges.map(\.id))
        let communityIds = Set(current.communities.map(\.id))
        let clusterIds = Set(current.clusters.map(\.id))
        let nodes = current.nodes + page.nodes.filter { !nodeIds.contains($0.id) }
        let edges = current.edges + page.edges.filter { !edgeIds.contains($0.id) }
        return Graph3DResponse(
            nodes: nodes,
            edges: edges,
            clusters: current.clusters + page.clusters.filter { !clusterIds.contains($0.id) },
            communities: current.communities + page.communities.filter { !communityIds.contains($0.id) },
            totalNodes: nodes.count,
            totalEdges: edges.count
        )
    }

    func reload(selecting id: String?) async {
        await load()
        if let id, graph.nodes.contains(where: { $0.id == id }) {
            selectedNodeId = id
        }
    }

    func select(nodeId: String?) {
        selectedNodeId = nodeId
        activeSheet = nil
        if nodeId == nil {
            isolateCommunity = false
            cardExpanded = false
        } else {
            // The inspector needs the room on a phone.
            showControls = false
        }
    }

    /// Selects a concept by id or (case-insensitive) name. Returns false when it isn't in the graph.
    @discardableResult
    func focus(_ idOrName: String) -> Bool {
        let needle = idOrName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !needle.isEmpty else { return false }
        let match = graph.nodes.first { $0.id == needle }
            ?? graph.nodes.first { $0.name.caseInsensitiveCompare(needle) == .orderedSame }
            ?? graph.nodes.first { $0.name.localizedCaseInsensitiveContains(needle) }
        guard let match else { return false }
        filter = .all
        select(nodeId: match.id)
        return true
    }

    func openNotes() { activeSheet = .notes }
    func openLinks() { activeSheet = .links }
    func openQuiz() { activeSheet = .quiz }
    func closeSheet() { activeSheet = nil }

    func toggleCommunityFocus() {
        isolateCommunity.toggle()
    }

    func resetCamera() {
        resetCameraToken &+= 1
    }

    // MARK: - Relationships

    func community(containing id: String) -> GraphCommunity? {
        graph.communities.first { $0.entityIds.contains(id) }
    }

    /// Parent / current / child communities for the Inspector hierarchy (web `hierarchyInfo`).
    func communityHierarchy(for id: String) -> (parents: [GraphCommunity], current: GraphCommunity, children: [GraphCommunity])? {
        guard let current = community(containing: id) else { return nil }
        let parents = graph.communities.filter { current.parent != nil && $0.id == current.parent }
        let children = graph.communities.filter { $0.parent == current.id }
        return (parents, current, children)
    }

    /// The five heaviest links touching `id` (web "Strongest Relationships").
    func strongestRelationships(of id: String) -> [(edge: GraphEdge, node: GraphNode)] {
        let byId = nodesById
        return graph.edges
            .filter { $0.source == id || $0.target == id }
            .sorted { ($0.strength ?? 0.6) > ($1.strength ?? 0.6) }
            .compactMap { edge in
                let other = edge.source == id ? edge.target : edge.source
                return byId[other].map { (edge, $0) }
            }
            .prefix(5)
            .map { $0 }
    }

    func neighbors(of id: String) -> [(node: GraphNode, relationship: String)] {
        let byId = nodesById
        var seen = Set<String>()
        return graph.edges
            .filter { $0.source == id || $0.target == id }
            .sorted { ($0.strength ?? 0) > ($1.strength ?? 0) }
            .compactMap { edge in
                let other = edge.source == id ? edge.target : edge.source
                guard !seen.contains(other), let node = byId[other] else { return nil }
                seen.insert(other)
                return (node, (edge.relationshipType ?? "RELATED_TO").uppercased())
            }
    }

    /// Concepts that should be understood before `id` (A PREREQUISITE_OF id, id BUILDS_ON B).
    func prerequisites(of id: String) -> [GraphNode] {
        let byId = nodesById
        return graph.edges
            .sorted { ($0.strength ?? 0) > ($1.strength ?? 0) }
            .compactMap { edge -> GraphNode? in
                let rel = (edge.relationshipType ?? "").uppercased()
                if rel == "PREREQUISITE_OF", edge.target == id { return byId[edge.source] }
                if rel == "BUILDS_ON", edge.source == id { return byId[edge.target] }
                return nil
            }
    }

    /// Concepts that `id` unlocks.
    func unlocks(of id: String) -> [GraphNode] {
        let byId = nodesById
        return graph.edges
            .sorted { ($0.strength ?? 0) > ($1.strength ?? 0) }
            .compactMap { edge -> GraphNode? in
                let rel = (edge.relationshipType ?? "").uppercased()
                if rel == "PREREQUISITE_OF", edge.source == id { return byId[edge.target] }
                if rel == "BUILDS_ON", edge.target == id { return byId[edge.source] }
                return nil
            }
    }

    /// Up to three prerequisite steps, the concept itself, then up to two concepts it unlocks.
    func learningPath(to id: String) -> [GraphNode] {
        var chain: [GraphNode] = []
        var visited: Set<String> = [id]
        var cursor = id
        for _ in 0..<3 {
            guard let previous = prerequisites(of: cursor).first(where: { !visited.contains($0.id) }) else { break }
            chain.insert(previous, at: 0)
            visited.insert(previous.id)
            cursor = previous.id
        }
        if let node = nodesById[id] { chain.append(node) }
        chain.append(contentsOf: unlocks(of: id).filter { !visited.contains($0.id) }.prefix(2))
        return chain
    }

    // MARK: - Merge mode

    func enterMergeMode() {
        guard selectedNodeId != nil else { return }
        activeSheet = nil
        mergeTargetIds = []
        mergeMode = true
    }

    func exitMergeMode() {
        mergeMode = false
        mergeTargetIds = []
    }

    func toggleMergeTarget(_ id: String) {
        guard id != selectedNodeId else { return }
        if mergeTargetIds.contains(id) {
            mergeTargetIds.remove(id)
        } else {
            mergeTargetIds.insert(id)
        }
    }

    /// Folds every merge target into the selected concept (`POST /api/concepts/merge`).
    func performMerge() async -> Bool {
        guard let source = selectedNode, !mergeTargetIds.isEmpty, !isMerging else { return false }
        let count = mergeTargetIds.count
        if usingStub {
            showToast("Demo graph — merge skipped")
            exitMergeMode()
            return false
        }
        isMerging = true
        defer { isMerging = false }
        do {
            try await APIClient.shared.mergeConcepts(sourceIds: Array(mergeTargetIds), into: source.id)
            exitMergeMode()
            await reload(selecting: source.id)
            showToast("Merged \(count) concept\(count == 1 ? "" : "s") into \(source.name)")
            return true
        } catch {
            showToast(APIError.userFacing(error, resource: "merge"))
            return false
        }
    }

    // MARK: - Create concept

    func openCreate(name: String = "", position: GraphPoint3D? = nil) {
        guard !mergeMode else { return }
        createDraft = CreateConceptDraft(name: name, position: position)
    }

    /// `POST /api/nodes`, then reload and queue link suggestions for the new concept.
    func createConcept(
        name: String,
        description: String,
        domain: String,
        parentId: String?,
        position: GraphPoint3D?
    ) async throws {
        if usingStub {
            showToast("Demo graph — concept not saved")
            return
        }
        let trimmedDescription = description.trimmingCharacters(in: .whitespacesAndNewlines)
        let id = try await APIClient.shared.createNode(
            name: name.trimmingCharacters(in: .whitespacesAndNewlines),
            description: trimmedDescription.isEmpty ? nil : trimmedDescription,
            domain: domain,
            parentConceptId: parentId,
            position: position
        )
        await reload(selecting: id)
        showToast("Added \(name)")
        if let id, selectedNodeId == id {
            pendingLinkSuggestionsId = id
        }
    }

    /// Opens link suggestions once the create sheet has finished dismissing.
    func createSheetDismissed() {
        guard let id = pendingLinkSuggestionsId else { return }
        pendingLinkSuggestionsId = nil
        if selectedNodeId == id { toolSheet = .suggestLinks }
    }

    // MARK: - Search

    func updateSearch() {
        searchTask?.cancel()
        let q = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else {
            searchResults = []
            isSearching = false
            return
        }
        searchTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 280_000_000)
            guard !Task.isCancelled, let self else { return }
            await self.runSearch(q)
        }
    }

    private func runSearch(_ q: String) async {
        isSearching = true
        defer { isSearching = false }
        let local = filteredNodes.prefix(12).map {
            GraphSearchResult(id: $0.id, name: $0.name, domain: $0.domain, color: $0.color)
        }
        guard !usingStub else {
            searchResults = Array(local)
            return
        }
        do {
            let remote = try await APIClient.shared.searchConcepts(q)
            searchResults = remote.isEmpty ? Array(local) : remote
        } catch {
            searchResults = Array(local)
        }
    }

    // MARK: - Communities

    /// POST /api/graph3d/communities/recompute, then reload (graceful fallback).
    func recomputeCommunities() async {
        guard !isRecomputingCommunities else { return }
        isRecomputingCommunities = true
        defer { isRecomputingCommunities = false }

        if usingStub {
            showToast("Demo graph — recompute skipped")
            return
        }

        do {
            let result = try await APIClient.shared.recomputeCommunities()
            let count = result.count.map(String.init) ?? "?"
            showToast("Communities recomputed (\(count))")
            await load()
        } catch {
            showToast("Recompute unavailable — showing current communities")
            errorMessage = Self.sanitizeError(error)
        }
    }

    func showToast(_ message: String) {
        toast = message
        toastTask?.cancel()
        toastTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 2_400_000_000)
            guard !Task.isCancelled else { return }
            toast = nil
        }
    }

    private static func sanitizeError(_ error: Error) -> String {
        APIError.userFacing(error, resource: "graph")
    }

    static func stubGraph() -> Graph3DResponse {
        let nodes = [
            GraphNode(id: "n1", name: "GraphRAG", definition: "Retrieval over a knowledge graph", domain: "Machine Learning", masteryLevel: 0.64, size: 1.6, color: "#7C3AED"),
            GraphNode(id: "n2", name: "SM-2", definition: "Spaced repetition algorithm", domain: "Learning Science", masteryLevel: 0.82, size: 1.2, color: "#2EFFE6"),
            GraphNode(id: "n3", name: "Neo4j", definition: "Property graph store", domain: "Database Systems", masteryLevel: 0.35, size: 1.3, color: "#F59E0B"),
            GraphNode(id: "n4", name: "LangGraph", definition: "Agent orchestration", domain: "Machine Learning", masteryLevel: 0.22, size: 1.4, color: "#7C3AED"),
            GraphNode(id: "n5", name: "Active Recall", definition: "Practice by retrieving", domain: "Learning Science", masteryLevel: 0.9, size: 1.1, color: "#2EFFE6"),
            GraphNode(id: "n6", name: "Embeddings", definition: "Vector representations", domain: "Machine Learning", masteryLevel: 0.71, size: 1.25, color: "#7C3AED"),
            GraphNode(id: "n7", name: "Cypher", definition: "Graph query language", domain: "Database Systems", masteryLevel: 0.3, size: 1.05, color: "#F59E0B"),
            GraphNode(id: "n8", name: "Bloom", definition: "Graph visualization", domain: "Database Systems", size: 0.95, color: "#F59E0B"),
            GraphNode(id: "n9", name: "Interleaving", definition: "Mix practice topics", domain: "Learning Science", masteryLevel: 0.55, size: 1.0, color: "#2EFFE6"),
            GraphNode(id: "n10", name: "Force Layout", definition: "Physics-based placement", domain: "Computer Science", masteryLevel: 0.48, size: 1.15, color: "#10B981"),
        ]
        let edges = [
            GraphEdge(source: "n6", target: "n1", relationshipType: "PREREQUISITE_OF", strength: 0.8),
            GraphEdge(source: "n1", target: "n3", relationshipType: "USES", strength: 0.9),
            GraphEdge(source: "n1", target: "n4", relationshipType: "ORCHESTRATED_BY", strength: 0.85),
            GraphEdge(source: "n2", target: "n5", relationshipType: "SUPPORTS", strength: 0.88),
            GraphEdge(source: "n5", target: "n1", relationshipType: "RELATED_TO", strength: 0.6),
            GraphEdge(source: "n3", target: "n4", relationshipType: "PREREQUISITE_OF", strength: 0.55),
            GraphEdge(source: "n3", target: "n7", relationshipType: "PART_OF", strength: 0.7),
            GraphEdge(source: "n3", target: "n8", relationshipType: "RELATED_TO", strength: 0.5),
            GraphEdge(source: "n5", target: "n9", relationshipType: "RELATED_TO", strength: 0.65),
            GraphEdge(source: "n10", target: "n1", relationshipType: "RELATED_TO", strength: 0.45),
            GraphEdge(source: "n4", target: "n6", relationshipType: "BUILDS_ON", strength: 0.6),
            GraphEdge(source: "n7", target: "n3", relationshipType: "SUBTOPIC_OF", strength: 0.7),
        ]
        let communities = [
            GraphCommunity(id: "c0", title: "Knowledge Systems", label: "Knowledge Systems", size: 9, level: 1, entityIds: ["n1", "n2", "n3", "n4", "n5", "n6", "n7", "n8", "n9"]),
            GraphCommunity(id: "c1", title: "Graph Stack", label: "Graph Stack", size: 6, level: 0, parent: "c0", entityIds: ["n1", "n3", "n4", "n6", "n7", "n8"]),
            GraphCommunity(id: "c2", title: "Learning Science", label: "Learning Science", size: 3, level: 0, parent: "c0", entityIds: ["n2", "n5", "n9"]),
            GraphCommunity(id: "c3", title: "Layout", label: "Layout", size: 1, level: 0, entityIds: ["n10"]),
        ]
        return Graph3DResponse(
            nodes: nodes,
            edges: edges,
            clusters: [
                GraphCluster(id: "Machine Learning", label: "Machine Learning", color: "#7C3AED"),
                GraphCluster(id: "Learning Science", label: "Learning Science", color: "#2EFFE6"),
                GraphCluster(id: "Database Systems", label: "Database Systems", color: "#F59E0B"),
                GraphCluster(id: "Computer Science", label: "Computer Science", color: "#10B981"),
            ],
            communities: communities,
            totalNodes: nodes.count,
            totalEdges: edges.count
        )
    }
}
