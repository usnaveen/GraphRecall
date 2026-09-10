import SwiftUI
import WebKit

/// WKWebView host for force-graph — visual parity toward web GraphVisualizer.
struct GraphForceWebView: UIViewRepresentable {
    let graph: Graph3DResponse
    var highlightIds: Set<String> = []
    var isDemo: Bool = false
    var focusIds: Set<String> = []
    var selectedId: String? = nil
    var onSelect: ((String?) -> Void)?
    var onCommunitiesRecompute: (() -> Void)?

    func makeCoordinator() -> Coordinator {
        Coordinator(onSelect: onSelect, onCommunitiesRecompute: onCommunitiesRecompute)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.preferences.javaScriptCanOpenWindowsAutomatically = false
        let userController = config.userContentController
        userController.add(context.coordinator, name: "graphBridge")

        let canvas = UIColor(red: 7 / 255, green: 7 / 255, blue: 10 / 255, alpha: 1) // #07070A
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.isOpaque = true
        webView.backgroundColor = canvas
        webView.underPageBackgroundColor = canvas
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.backgroundColor = canvas
        webView.navigationDelegate = context.coordinator
        context.coordinator.webView = webView

        if let url = Bundle.main.url(forResource: "graph_force", withExtension: "html") {
            webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        } else {
            let fallback = """
            <html><body style="background:#07070A;color:#B6FF2E;font-family:-apple-system;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
            Loading graph…
            </body></html>
            """
            webView.loadHTMLString(fallback, baseURL: nil)
        }
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.onSelect = onSelect
        context.coordinator.onCommunitiesRecompute = onCommunitiesRecompute
        context.coordinator.pendingGraph = graph
        context.coordinator.pendingHighlight = highlightIds
        context.coordinator.pendingFocus = focusIds
        context.coordinator.pendingSelectedId = selectedId
        context.coordinator.pendingDemo = isDemo
        if context.coordinator.pageReady {
            context.coordinator.pushGraph()
        }
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        var onSelect: ((String?) -> Void)?
        var onCommunitiesRecompute: (() -> Void)?
        weak var webView: WKWebView?
        var pageReady = false
        var pendingGraph: Graph3DResponse?
        var pendingHighlight: Set<String> = []
        var pendingFocus: Set<String> = []
        var pendingSelectedId: String?
        var pendingDemo = false
        private var lastPushSignature: String?

        init(onSelect: ((String?) -> Void)?, onCommunitiesRecompute: (() -> Void)?) {
            self.onSelect = onSelect
            self.onCommunitiesRecompute = onCommunitiesRecompute
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "graphBridge" else { return }
            if let body = message.body as? [String: Any] {
                if let type = body["type"] as? String {
                    switch type {
                    case "ready":
                        pageReady = true
                        lastPushSignature = nil
                        pushGraph()
                        return
                    case "communities.recompute":
                        onCommunitiesRecompute?()
                        return
                    default:
                        break
                    }
                }
                if let id = body["id"] as? String {
                    onSelect?(id)
                } else if body["id"] is NSNull {
                    onSelect?(nil)
                }
            } else if let id = message.body as? String {
                onSelect?(id)
            }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            pageReady = true
            lastPushSignature = nil
            pushGraph()
        }

        func pushGraph() {
            guard let webView, let graph = pendingGraph else { return }
            let payload = graphPayload(graph)
            guard let data = try? JSONSerialization.data(withJSONObject: payload),
                  let json = String(data: data, encoding: .utf8)
            else { return }
            let highlights = Array(pendingHighlight.union(pendingFocus))
            let hlData = (try? JSONSerialization.data(withJSONObject: highlights)).flatMap { String(data: $0, encoding: .utf8) } ?? "[]"
            var opts: [String: Any] = [
                "demo": pendingDemo,
                "focusIds": Array(pendingFocus)
            ]
            if let selected = pendingSelectedId {
                opts["selectedId"] = selected
            } else {
                opts["selectedId"] = NSNull()
            }
            let optsData = (try? JSONSerialization.data(withJSONObject: opts)).flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
            let signature = json + "|" + hlData + "|" + optsData
            guard signature != lastPushSignature else { return }
            lastPushSignature = signature
            let js = "window.setGraphData && window.setGraphData(\(json), \(hlData), \(optsData));"
            webView.evaluateJavaScript(js, completionHandler: nil)
        }

        private func graphPayload(_ graph: Graph3DResponse) -> [String: Any] {
            // Degree for web-like sizing when backend size is missing / flat.
            var degree: [String: Int] = [:]
            for e in graph.edges {
                degree[e.source, default: 0] += 1
                degree[e.target, default: 0] += 1
            }

            let nodes: [[String: Any]] = graph.nodes.map { n in
                let deg = degree[n.id] ?? 0
                // Mirror web calculateNodeSize(degree, frequency≈1): clamp 1.5…10
                let computed = max(1.5, min(10.0, 2.0 + Double(deg) * 0.4 + 0.2))
                var dict: [String: Any] = [
                    "id": n.id,
                    "name": n.name,
                    "val": n.size ?? computed,
                    "degree": deg
                ]
                if let domain = n.domain { dict["domain"] = domain }
                if let color = n.color { dict["color"] = color }
                if let definition = n.definition { dict["definition"] = definition }
                if let x = n.x { dict["x"] = x }
                if let y = n.y { dict["y"] = y }
                return dict
            }
            let links: [[String: Any]] = graph.edges.map { e in
                var dict: [String: Any] = [
                    "source": e.source,
                    "target": e.target
                ]
                if let t = e.relationshipType { dict["type"] = t }
                if let s = e.strength { dict["strength"] = s }
                return dict
            }
            let communities: [[String: Any]] = graph.communities.map { c in
                var dict: [String: Any] = ["id": c.id]
                if let title = c.title { dict["title"] = title }
                if let label = c.label { dict["label"] = label }
                if let size = c.size { dict["size"] = size }
                if let level = c.level { dict["level"] = level }
                if let parent = c.parent { dict["parent"] = parent }
                if !c.entityIds.isEmpty { dict["entity_ids"] = c.entityIds }
                return dict
            }
            return [
                "nodes": nodes,
                "links": links,
                "communities": communities
            ]
        }
    }
}
