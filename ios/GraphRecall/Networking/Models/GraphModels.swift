import Foundation

struct Graph3DResponse: Codable {
    let nodes: [GraphNode]
    let edges: [GraphEdge]
}

struct GraphNode: Codable, Identifiable {
    let id: String
    let name: String?
    let domain: String?
}

struct GraphEdge: Codable, Identifiable {
    var id: String { "\(source)-\(target)" }
    let source: String
    let target: String
}
