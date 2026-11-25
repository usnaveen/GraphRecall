import SwiftUI

/// Everything agents send, in one sheet: insights from the always-on agent, and cards an outside
/// agent (over MCP) suggested for the feed, which wait for approval.
struct AgentHubSheet: View {
    enum Tab: String, Hashable {
        case insights, suggestions
    }

    let feed: FeedViewModel
    let showsSuggestions: Bool
    @State private var tab: Tab
    @State private var inbox = AgentInboxViewModel()
    @Environment(\.dismiss) private var dismiss
    private let bridge = AgentBridgeCapability.shared

    init(feed: FeedViewModel, showsSuggestions: Bool, startOn: Tab = .insights) {
        self.feed = feed
        self.showsSuggestions = showsSuggestions
        _tab = State(initialValue: showsSuggestions ? startOn : .insights)
    }

    var body: some View {
        @Bindable var inboxBinding = inbox
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                GRBackdropGlow()

                VStack(spacing: 8) {
                    if showsSuggestions {
                        Picker("Show", selection: $tab) {
                            Text(insightsTitle).tag(Tab.insights)
                            Text(suggestionsTitle).tag(Tab.suggestions)
                        }
                        .pickerStyle(.segmented)
                        .padding(.horizontal, 20)
                        .padding(.top, 4)
                    }

                    switch tab {
                    case .insights:
                        AgentInsightsList(model: feed)
                    case .suggestions:
                        AgentInboxContent(model: inbox, showsFilterPicker: false)
                    }
                }
            }
            .navigationTitle("Agent Inbox")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
                if tab == .suggestions {
                    ToolbarItem(placement: .primaryAction) {
                        Menu {
                            Picker("Show", selection: $inboxBinding.filter) {
                                ForEach(AgentInboxViewModel.Filter.allCases) { Text($0.title).tag($0) }
                            }
                            if inbox.filter == .pending && inbox.items.count > 1 {
                                Divider()
                                Button("Approve all", systemImage: "checkmark.circle") {
                                    Task { await inbox.approveAll() }
                                }
                            }
                        } label: {
                            Label("Filter", systemImage: "line.3.horizontal.decrease.circle")
                        }
                    }
                }
            }
        }
    }

    private var insightsTitle: String {
        feed.agentInsights.isEmpty ? "Insights" : "Insights \u{00B7} \(feed.agentInsights.count)"
    }

    private var suggestionsTitle: String {
        bridge.pendingCount > 0 ? "Suggestions \u{00B7} \(bridge.pendingCount)" : "Suggestions"
    }
}
