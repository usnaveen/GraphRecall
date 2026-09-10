import Foundation

struct Graph3DResponse: Decodable {
    let nodes: [GraphNode]
    let edges: [GraphEdge]
    let clusters: [GraphCluster]
    let communities: [GraphCommunity]
    let totalNodes: Int
    let totalEdges: Int

    enum CodingKeys: String, CodingKey {
        case nodes, edges, clusters, communities
        case totalNodes = "total_nodes"
        case totalEdges = "total_edges"
    }

    init(
        nodes: [GraphNode] = [],
        edges: [GraphEdge] = [],
        clusters: [GraphCluster] = [],
        communities: [GraphCommunity] = [],
        totalNodes: Int = 0,
        totalEdges: Int = 0
    ) {
        self.nodes = nodes
        self.edges = edges
        self.clusters = clusters
        self.communities = communities
        self.totalNodes = totalNodes
        self.totalEdges = totalEdges
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        nodes = try c.decodeIfPresent([GraphNode].self, forKey: .nodes) ?? []
        edges = try c.decodeIfPresent([GraphEdge].self, forKey: .edges) ?? []
        clusters = try c.decodeIfPresent([GraphCluster].self, forKey: .clusters) ?? []
        communities = try c.decodeIfPresent([GraphCommunity].self, forKey: .communities) ?? []
        totalNodes = try c.decodeIfPresent(Int.self, forKey: .totalNodes) ?? nodes.count
        totalEdges = try c.decodeIfPresent(Int.self, forKey: .totalEdges) ?? edges.count
    }
}

struct GraphNode: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let definition: String?
    let domain: String?
    let complexityScore: Double?
    let masteryLevel: Double?
    let confidence: Double?
    let x: Double?
    let y: Double?
    let z: Double?
    let size: Double?
    let color: String?

    enum CodingKeys: String, CodingKey {
        case id, name, definition, domain, confidence, x, y, z, size, color
        case complexityScore = "complexity_score"
        case masteryLevel = "mastery_level"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? "Untitled"
        definition = try c.decodeIfPresent(String.self, forKey: .definition)
        domain = try c.decodeIfPresent(String.self, forKey: .domain)
        complexityScore = try c.decodeIfPresent(Double.self, forKey: .complexityScore)
        masteryLevel = try c.decodeIfPresent(Double.self, forKey: .masteryLevel)
        confidence = try c.decodeIfPresent(Double.self, forKey: .confidence)
        x = try c.decodeIfPresent(Double.self, forKey: .x)
        y = try c.decodeIfPresent(Double.self, forKey: .y)
        z = try c.decodeIfPresent(Double.self, forKey: .z)
        size = try c.decodeIfPresent(Double.self, forKey: .size)
        color = try c.decodeIfPresent(String.self, forKey: .color)
    }

    init(
        id: String,
        name: String,
        definition: String? = nil,
        domain: String? = nil,
        complexityScore: Double? = nil,
        masteryLevel: Double? = nil,
        confidence: Double? = nil,
        x: Double? = nil,
        y: Double? = nil,
        z: Double? = nil,
        size: Double? = nil,
        color: String? = nil
    ) {
        self.id = id
        self.name = name
        self.definition = definition
        self.domain = domain
        self.complexityScore = complexityScore
        self.masteryLevel = masteryLevel
        self.confidence = confidence
        self.x = x
        self.y = y
        self.z = z
        self.size = size
        self.color = color
    }
}

struct GraphEdge: Decodable, Identifiable, Hashable {
    var id: String
    let source: String
    let target: String
    let relationshipType: String?
    let strength: Double?
    let mentionCount: Int?

    enum CodingKeys: String, CodingKey {
        case id, source, target, strength
        case relationshipType = "relationship_type"
        case mentionCount = "mention_count"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        source = try c.decode(String.self, forKey: .source)
        target = try c.decode(String.self, forKey: .target)
        relationshipType = try c.decodeIfPresent(String.self, forKey: .relationshipType)
        strength = try c.decodeIfPresent(Double.self, forKey: .strength)
        mentionCount = try c.decodeIfPresent(Int.self, forKey: .mentionCount)
        if let explicit = try c.decodeIfPresent(String.self, forKey: .id) {
            id = explicit
        } else {
            id = "\(source)-\(target)"
        }
    }

    init(
        id: String? = nil,
        source: String,
        target: String,
        relationshipType: String? = nil,
        strength: Double? = nil,
        mentionCount: Int? = nil
    ) {
        self.source = source
        self.target = target
        self.relationshipType = relationshipType
        self.strength = strength
        self.mentionCount = mentionCount
        self.id = id ?? "\(source)-\(target)"
    }
}

struct GraphCluster: Decodable, Hashable, Identifiable {
    var id: String
    let label: String?
    let color: String?

    init(id: String, label: String? = nil, color: String? = nil) {
        self.id = id
        self.label = label
        self.color = color
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: DynamicCodingKeys.self)
        id = try c.decodeIfPresent(String.self, forKey: DynamicCodingKeys("id"))
            ?? c.decodeIfPresent(String.self, forKey: DynamicCodingKeys("label"))
            ?? UUID().uuidString
        label = try c.decodeIfPresent(String.self, forKey: DynamicCodingKeys("label"))
            ?? c.decodeIfPresent(String.self, forKey: DynamicCodingKeys("id"))
        color = try c.decodeIfPresent(String.self, forKey: DynamicCodingKeys("color"))
    }
}

struct GraphCommunity: Decodable, Hashable, Identifiable {
    var id: String
    let title: String?
    let label: String?
    let size: Int?
    let level: Int?
    let parent: String?
    let entityIds: [String]

    init(
        id: String,
        title: String? = nil,
        label: String? = nil,
        size: Int? = nil,
        level: Int? = nil,
        parent: String? = nil,
        entityIds: [String] = []
    ) {
        self.id = id
        self.title = title
        self.label = label
        self.size = size
        self.level = level
        self.parent = parent
        self.entityIds = entityIds
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: DynamicCodingKeys.self)
        id = try c.decodeIfPresent(String.self, forKey: DynamicCodingKeys("id"))
            ?? UUID().uuidString
        title = try c.decodeIfPresent(String.self, forKey: DynamicCodingKeys("title"))
        label = try c.decodeIfPresent(String.self, forKey: DynamicCodingKeys("label"))
            ?? c.decodeIfPresent(String.self, forKey: DynamicCodingKeys("name"))
            ?? title
            ?? c.decodeIfPresent(String.self, forKey: DynamicCodingKeys("summary"))
        size = try c.decodeIfPresent(Int.self, forKey: DynamicCodingKeys("size"))
            ?? c.decodeIfPresent(Int.self, forKey: DynamicCodingKeys("member_count"))
        level = try c.decodeIfPresent(Int.self, forKey: DynamicCodingKeys("level"))
        parent = try c.decodeIfPresent(String.self, forKey: DynamicCodingKeys("parent"))
        entityIds = try c.decodeIfPresent([String].self, forKey: DynamicCodingKeys("entity_ids"))
            ?? c.decodeIfPresent([String].self, forKey: DynamicCodingKeys("entityIds"))
            ?? c.decodeIfPresent([String].self, forKey: DynamicCodingKeys("members"))
            ?? []
    }
}

struct CommunitiesRecomputeResponse: Decodable {
    let status: String?
    let count: Int?
}

private struct DynamicCodingKeys: CodingKey {
    var stringValue: String
    var intValue: Int? { nil }
    init(_ string: String) { stringValue = string }
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { nil }
}
