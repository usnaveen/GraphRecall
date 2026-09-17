import SwiftUI
import Observation

/// Cross-tab navigation: lets Feed, Graph, Search and Assistant hand work to each other
/// ("Open in graph", "Explain more", "Ask about this concept").
@MainActor
@Observable
final class AppRouter {
    var tab: GRTab
    var showSearch = false
    var openLibraryToken = 0
    /// Concept id or name the Graph tab should select when it next appears.
    var pendingGraphFocus: String?
    /// Prompt the Assistant sends when it next appears.
    var pendingAssistantPrompt: String?
    /// Concept the Assistant conversation is scoped to (shown as a removable chip).
    var assistantFocusTopic: String?
    /// Past conversation the Assistant should restore when it next appears.
    var pendingConversationId: String?
    /// Set by the widget / `graphrecall://review` — Today starts a session when it next appears.
    var pendingStartReview = false
    /// True while the software keyboard is on screen — Assistant tightens its composer.
    var isKeyboardVisible = false

    init(initialTab: GRTab = .feed) {
        tab = initialTab
    }

    func select(_ newTab: GRTab) {
        withAnimation(.spring(response: 0.35, dampingFraction: 0.78)) {
            tab = newTab
        }
    }

    func focusInGraph(_ concept: String) {
        pendingGraphFocus = concept
        select(.graph)
    }

    func ask(_ prompt: String, topic: String? = nil) {
        pendingAssistantPrompt = prompt
        if let topic, !topic.isEmpty { assistantFocusTopic = topic }
        select(.assistant)
    }

    func openConversation(_ id: String) {
        pendingConversationId = id
        select(.assistant)
    }

    /// `graphrecall://review` starts a review, `graphrecall://create` opens Create (share inbox).
    func handleDeepLink(_ url: URL) {
        guard url.scheme == GRShared.urlScheme else { return }
        switch url.host() {
        case "review":
            pendingStartReview = true
            select(.feed)
        case "create":
            select(.create)
        case "today":
            select(.feed)
        default:
            break
        }
    }
}
