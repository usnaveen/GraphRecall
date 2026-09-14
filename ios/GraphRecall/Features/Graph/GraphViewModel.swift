import Foundation
import Observation

@MainActor
@Observable
final class GraphViewModel {
    var graph = Graph3DResponse()
    var isLoading = false
    var isRecomputingCommunities = false
    var errorMessage: String?
    var usingStub = false
    var selectedNodeId: String?
    var searchQuery: String = ""
    var isolateCommunity = false
    var communityRecomputeNotice: String?
    var activeSheet: InspectorSheet?
    var filter: GraphFilter = .all
    var searchResults: [GraphSearchResult] = []
    var isSearching = false
    /// Concept shown in the full-screen Concept detail sheet.
    var detailNode: GraphNode?
    var toolSheet: ToolSheet?
    var toast: String?
    @ObservationIgnored private var searchTask: Task<Void, Never>?
    @ObservationIgnored private var toastTask: Task<Void, Never>?

    enum InspectorSheet: String, Identifiable {
        case notes, links, quiz
        var id: String { rawValue }
    }

    enum ToolSheet: String, Identifiable {
        case suggestLinks, merge
        var id: String { rawValue }
    }

    enum GraphFilter: Hashable {
        case all, weak, domain(String)
    }

    static let weakThreshold = 0.4

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

    var focusCommunityIds: Set<String> {
        guard isolateCommunity, let selectedNodeId else { return [] }
        guard let community = graph.communities.first(where: { $0.entityIds.contains(selectedNodeId) }) else {
            return []
        }
        return Set(community.entityIds)
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

    var weakNodeIds: Set<String> {
        Set(graph.nodes.filter { ($0.masteryLevel ?? 0) < Self.weakThreshold }.map(\.id))
    }

    /// Ids the WebView should highlight: community focus → search → filter → selection.
    var highlightSet: Set<String> {
        if !focusCommunityIds.isEmpty { return focusCommunityIds }
        if !searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return Set(filteredNodes.map(\.id))
        }
        switch filter {
        case .all: break
        case .weak: return weakNodeIds
        case .domain(let d): return Set(graph.nodes.filter { $0.domain == d }.map(\.id))
        }
        if let id = selectedNodeId { return [id] }
        return []
    }

    // MARK: - Loading

    func load() async {
        isLoading = true
        errorMessage = nil
        communityRecomputeNotice = nil
        defer { isLoading = false }

        do {
            let response = try await APIClient.shared.fetchGraph()
            graph = response
            usingStub = false
            if let selectedNodeId, !response.nodes.contains(where: { $0.id == selectedNodeId }) {
                self.selectedNodeId = nil
            }
        } catch {
            errorMessage = Self.sanitizeError(error)
            graph = Self.stubGraph()
            usingStub = true
        }
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

    // MARK: - Relationships

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

    /// Bridge from WebView Controls → POST /api/graph3d/communities/recompute (graceful fallback).
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
            let response = try await APIClient.shared.fetchGraph()
            graph = response
            usingStub = false
            if let selectedNodeId, !response.nodes.contains(where: { $0.id == selectedNodeId }) {
                self.selectedNodeId = nil
            }
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
        ]
        let communities = [
            GraphCommunity(id: "c1", title: "Graph Stack", label: "Graph Stack", size: 6, level: 0, entityIds: ["n1", "n3", "n4", "n6", "n7", "n8"]),
            GraphCommunity(id: "c2", title: "Learning Science", label: "Learning Science", size: 3, level: 0, entityIds: ["n2", "n5", "n9"]),
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
