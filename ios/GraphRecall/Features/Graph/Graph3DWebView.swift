import SwiftUI
import WebKit

/// How the 3D scene colours concepts.
enum GraphColorMode: String, CaseIterable, Identifiable, Equatable {
    case domain, mastery, community

    var id: String { rawValue }

    var title: String {
        switch self {
        case .domain: "Domain"
        case .mastery: "Mastery"
        case .community: "Community"
        }
    }
}

/// Inputs to the 3D scene.
struct GraphSceneState: Equatable {
    var selectedId: String?
    /// Search matches / weak-spot lens: drawn larger, everything else dims.
    var highlightIds: Set<String> = []
    /// When set, only these nodes render (community isolation).
    var visibleIds: Set<String>?
    /// When set, only this domain renders.
    var domain: String?
    var minWeight: Double = 0
    var colorMode: GraphColorMode = .domain
    var mergeMode = false
    var mergeTargetIds: Set<String> = []
}

enum Graph3DEvent {
    case select(String?)
    case mergeToggle(String)
    /// Long press on empty space — create a concept at this world position.
    case createAt(GraphPoint3D)
    case layout(running: Bool)
}

/// WKWebView host for the Three.js graph scene.
/// Page source: `ios/Tools/graph3d/src/graph3d.js` → `WebAssets/graph3d.bundle.js`.
struct Graph3DWebView: UIViewRepresentable {
    let graph: Graph3DResponse
    /// Bumped whenever `graph` is replaced, so the page only re-runs its layout for new data.
    let graphVersion: Int
    let state: GraphSceneState
    /// Fraction of the canvas height covered by native UI along the bottom edge. The scene keeps
    /// the focused concept centred in the space above it.
    var insetBottom: Double = 0
    var resetCameraToken = 0
    var onEvent: (Graph3DEvent) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onEvent: onEvent)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: Coordinator.bridgeName)

        let background = UIColor(red: 10 / 255, green: 10 / 255, blue: 15 / 255, alpha: 1)
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.isOpaque = true
        webView.backgroundColor = background
        webView.underPageBackgroundColor = background
        webView.scrollView.backgroundColor = background
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.allowsLinkPreview = false
        webView.accessibilityIdentifier = "graph3d.canvas"
        context.coordinator.webView = webView

        if let url = Bundle.main.url(forResource: "graph3d", withExtension: "html") {
            webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        }
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let coordinator = context.coordinator
        coordinator.onEvent = onEvent
        coordinator.pendingGraph = graph
        coordinator.pendingGraphVersion = graphVersion
        coordinator.pendingState = state
        coordinator.pendingInset = insetBottom
        coordinator.pendingResetToken = resetCameraToken
        coordinator.flush()
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: Coordinator.bridgeName)
    }

    @MainActor
    final class Coordinator: NSObject, WKScriptMessageHandler {
        static let bridgeName = "graphBridge"

        var onEvent: (Graph3DEvent) -> Void
        weak var webView: WKWebView?
        var pendingGraph = Graph3DResponse()
        var pendingGraphVersion = 0
        var pendingState = GraphSceneState()
        var pendingInset = 0.0
        var pendingResetToken = 0

        private var pageReady = false
        private var pushedGraphVersion: Int?
        private var pushedState: GraphSceneState?
        private var pushedInset: Double?
        private var pushedResetToken = 0

        init(onEvent: @escaping (Graph3DEvent) -> Void) {
            self.onEvent = onEvent
        }

        /// Sends whatever changed since the last push. Data goes first so the page lays out
        /// before it applies selection and filters.
        func flush() {
            guard pageReady, let webView else { return }
            if pushedGraphVersion != pendingGraphVersion {
                pushedGraphVersion = pendingGraphVersion
                if let json = Self.encode(GraphPayload(pendingGraph)) {
                    webView.evaluateJavaScript("window.setGraphData(\(json)); void 0;")
                }
            }
            if pushedState != pendingState {
                pushedState = pendingState
                if let json = Self.encode(StatePayload(pendingState)) {
                    webView.evaluateJavaScript("window.setGraphState(\(json)); void 0;")
                }
            }
            // Insets change every frame of a card animation; they only move the projection centre.
            if pushedInset.map({ abs($0 - pendingInset) > 0.002 }) ?? true {
                pushedInset = pendingInset
                webView.evaluateJavaScript("window.setGraphInsets(\(pendingInset)); void 0;")
            }
            if pushedResetToken != pendingResetToken {
                pushedResetToken = pendingResetToken
                webView.evaluateJavaScript("window.resetCamera(); void 0;")
            }
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == Self.bridgeName,
                  let body = message.body as? [String: Any],
                  let type = body["type"] as? String
            else { return }

            switch type {
            case "ready":
                // A reload (e.g. WebContent process restart) needs everything pushed again.
                pageReady = true
                pushedGraphVersion = nil
                pushedState = nil
                pushedInset = nil
                pushedResetToken = pendingResetToken
                flush()
            case "select":
                onEvent(.select(body["id"] as? String))
            case "mergeToggle":
                if let id = body["id"] as? String { onEvent(.mergeToggle(id)) }
            case "createAt":
                let point = GraphPoint3D(
                    x: (body["x"] as? Double) ?? 0,
                    y: (body["y"] as? Double) ?? 0,
                    z: (body["z"] as? Double) ?? 0
                )
                onEvent(.createAt(point))
            case "layout":
                onEvent(.layout(running: (body["running"] as? Bool) ?? false))
            default:
                break
            }
        }

        private static func encode<T: Encodable>(_ value: T) -> String? {
            guard let data = try? JSONEncoder().encode(value) else { return nil }
            return String(data: data, encoding: .utf8)
        }
    }
}

// MARK: - Page payloads

/// `/api/graph3d` shape.
private struct GraphPayload: Encodable {
    struct Node: Encodable {
        let id: String
        let name: String
        let domain: String?
        let size: Double?
        let color: String?
        let masteryLevel: Double?
        let x: Double?
        let y: Double?
        let z: Double?

        enum CodingKeys: String, CodingKey {
            case id, name, domain, size, color, x, y, z
            case masteryLevel = "mastery_level"
        }
    }

    struct Edge: Encodable {
        let id: String
        let source: String
        let target: String
        let relationshipType: String?
        let strength: Double?

        enum CodingKeys: String, CodingKey {
            case id, source, target, strength
            case relationshipType = "relationship_type"
        }
    }

    struct Community: Encodable {
        let id: String
        let level: Int?
        let entityIds: [String]

        enum CodingKeys: String, CodingKey {
            case id, level
            case entityIds = "entity_ids"
        }
    }

    let nodes: [Node]
    let edges: [Edge]
    let communities: [Community]

    init(_ graph: Graph3DResponse) {
        nodes = graph.nodes.map {
            Node(id: $0.id, name: $0.name, domain: $0.domain, size: $0.size, color: $0.color,
                 masteryLevel: $0.masteryLevel, x: $0.x, y: $0.y, z: $0.z)
        }
        edges = graph.edges.map {
            Edge(id: $0.id, source: $0.source, target: $0.target,
                 relationshipType: $0.relationshipType, strength: $0.strength)
        }
        communities = graph.communities.map {
            Community(id: $0.id, level: $0.level, entityIds: $0.entityIds)
        }
    }
}

private struct StatePayload: Encodable {
    let selectedId: String?
    let highlightIds: [String]
    let visibleIds: [String]?
    let domain: String?
    let minWeight: Double
    let colorMode: String
    let mergeMode: Bool
    let mergeTargetIds: [String]

    init(_ state: GraphSceneState) {
        selectedId = state.selectedId
        highlightIds = Array(state.highlightIds)
        visibleIds = state.visibleIds.map(Array.init)
        domain = state.domain
        minWeight = state.minWeight
        colorMode = state.colorMode.rawValue
        mergeMode = state.mergeMode
        mergeTargetIds = Array(state.mergeTargetIds)
    }
}
