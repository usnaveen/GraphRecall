import Foundation
import Observation

@MainActor
@Observable
final class GraphViewModel {
    var graph = Graph3DResponse()
    var isLoading = false
    var errorMessage: String?
    var usingStub = false
    var selectedNodeId: String?
    var searchQuery: String = ""

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

    var statsLabel: String {
        let comm = graph.communities.isEmpty ? "" : " · \(graph.communities.count) communities"
        return "\(graph.totalNodes) nodes · \(graph.totalEdges) edges\(comm)"
    }

    func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let response = try await APIClient.shared.fetchGraph()
            graph = response
            usingStub = false
            if selectedNodeId == nil {
                selectedNodeId = response.nodes.first?.id
            }
        } catch {
            errorMessage = Self.sanitizeError(error)
            graph = Self.stubGraph()
            usingStub = true
            selectedNodeId = graph.nodes.first?.id
        }
    }

    func select(nodeId: String?) {
        selectedNodeId = nodeId
    }

    private static func sanitizeError(_ error: Error) -> String {
        APIError.userFacing(error, resource: "graph")
    }

    static func stubGraph() -> Graph3DResponse {
        let nodes = [
            GraphNode(id: "n1", name: "GraphRAG", definition: "Retrieval over a knowledge graph", domain: "Machine Learning", size: 1.6, color: "#7C3AED"),
            GraphNode(id: "n2", name: "SM-2", definition: "Spaced repetition algorithm", domain: "Learning Science", size: 1.2, color: "#2EFFE6"),
            GraphNode(id: "n3", name: "Neo4j", definition: "Property graph store", domain: "Database Systems", size: 1.3, color: "#F59E0B"),
            GraphNode(id: "n4", name: "LangGraph", definition: "Agent orchestration", domain: "Machine Learning", size: 1.4, color: "#7C3AED"),
            GraphNode(id: "n5", name: "Active Recall", definition: "Practice by retrieving", domain: "Learning Science", size: 1.1, color: "#2EFFE6"),
            GraphNode(id: "n6", name: "Embeddings", definition: "Vector representations", domain: "Machine Learning", size: 1.25, color: "#7C3AED"),
            GraphNode(id: "n7", name: "Cypher", definition: "Graph query language", domain: "Database Systems", size: 1.05, color: "#F59E0B"),
            GraphNode(id: "n8", name: "Bloom", definition: "Graph visualization", domain: "Database Systems", size: 0.95, color: "#F59E0B"),
            GraphNode(id: "n9", name: "Interleaving", definition: "Mix practice topics", domain: "Learning Science", size: 1.0, color: "#2EFFE6"),
            GraphNode(id: "n10", name: "Force Layout", definition: "Physics-based placement", domain: "Computer Science", size: 1.15, color: "#10B981"),
        ]
        let edges = [
            GraphEdge(source: "n1", target: "n3", relationshipType: "USES", strength: 0.9),
            GraphEdge(source: "n1", target: "n4", relationshipType: "ORCHESTRATED_BY", strength: 0.85),
            GraphEdge(source: "n1", target: "n6", relationshipType: "USES", strength: 0.8),
            GraphEdge(source: "n2", target: "n5", relationshipType: "SUPPORTS", strength: 0.88),
            GraphEdge(source: "n5", target: "n1", relationshipType: "RELATED_TO", strength: 0.6),
            GraphEdge(source: "n4", target: "n3", relationshipType: "RELATED_TO", strength: 0.55),
            GraphEdge(source: "n3", target: "n7", relationshipType: "PART_OF", strength: 0.7),
            GraphEdge(source: "n3", target: "n8", relationshipType: "RELATED_TO", strength: 0.5),
            GraphEdge(source: "n5", target: "n9", relationshipType: "RELATED_TO", strength: 0.65),
            GraphEdge(source: "n10", target: "n1", relationshipType: "RELATED_TO", strength: 0.45),
            GraphEdge(source: "n6", target: "n4", relationshipType: "BUILDS_ON", strength: 0.6),
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
