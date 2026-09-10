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

    var statsLabel: String {
        "\(graph.totalNodes) nodes · \(graph.totalEdges) edges"
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
            errorMessage = error.localizedDescription
            graph = Self.stubGraph()
            usingStub = true
            selectedNodeId = graph.nodes.first?.id
        }
    }

    func select(nodeId: String?) {
        selectedNodeId = nodeId
    }

    static func stubGraph() -> Graph3DResponse {
        let nodes = [
            GraphNode(id: "n1", name: "GraphRAG", definition: "Retrieval over a knowledge graph", domain: "Machine Learning", size: 1.4, color: "#B6FF2E"),
            GraphNode(id: "n2", name: "SM-2", definition: "Spaced repetition algorithm", domain: "Learning Science", size: 1.1, color: "#2EFFE6"),
            GraphNode(id: "n3", name: "Neo4j", definition: "Property graph store", domain: "Database Systems", size: 1.2, color: "#3B82F6"),
            GraphNode(id: "n4", name: "LangGraph", definition: "Agent orchestration", domain: "Machine Learning", size: 1.3, color: "#7C3AED"),
            GraphNode(id: "n5", name: "Active Recall", definition: "Practice by retrieving", domain: "Learning Science", size: 1.0, color: "#F59E0B"),
        ]
        let edges = [
            GraphEdge(source: "n1", target: "n3", relationshipType: "USES", strength: 0.9),
            GraphEdge(source: "n1", target: "n4", relationshipType: "ORCHESTRATED_BY", strength: 0.8),
            GraphEdge(source: "n2", target: "n5", relationshipType: "SUPPORTS", strength: 0.85),
            GraphEdge(source: "n5", target: "n1", relationshipType: "RELATED_TO", strength: 0.6),
            GraphEdge(source: "n4", target: "n3", relationshipType: "RELATED_TO", strength: 0.5),
        ]
        return Graph3DResponse(
            nodes: nodes,
            edges: edges,
            clusters: [],
            communities: [],
            totalNodes: nodes.count,
            totalEdges: edges.count
        )
    }
}
