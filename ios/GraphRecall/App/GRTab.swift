import SwiftUI

enum GRTab: String, CaseIterable, Identifiable {
    case feed, graph, create, assistant, profile
    var id: String { rawValue }

    var title: String {
        switch self {
        case .feed: return "Feed"
        case .graph: return "Graph"
        case .create: return "Create"
        case .assistant: return "Assistant"
        case .profile: return "Profile"
        }
    }

    var systemImage: String {
        switch self {
        case .feed: return "house.fill"
        case .graph: return "point.3.connected.trianglepath.dotted"
        case .create: return "plus"
        case .assistant: return "bubble.left.and.bubble.right.fill"
        case .profile: return "person.fill"
        }
    }
}
