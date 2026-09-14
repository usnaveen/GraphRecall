import SwiftUI

/// Full concept page: mastery, definition, learning path, connections, cards and sources.
struct ConceptDetailView: View {
    let node: GraphNode
    let graph: GraphViewModel

    @Environment(\.dismiss) private var dismiss
    @Environment(AppRouter.self) private var router
    @State private var focus: ConceptFocusResponse?
    @State private var resources: [ConceptResource] = []
    @State private var cards: [QuizHistoryItem] = []
    @State private var showQuiz = false

    private var mastery: Double { focus?.center.masteryLevel ?? node.masteryLevel ?? 0 }
    private var isWeak: Bool { mastery < GraphViewModel.weakThreshold }
    private var nodeColor: Color { Color(hex: node.color ?? "") ?? GRColor.accent }

    private var definition: String {
        let text = focus?.center.definition ?? node.definition ?? ""
        return text.isEmpty ? "No definition yet — ingest a source that mentions \(node.name)." : text
    }

    var body: some View {
        let neighbors = graph.neighbors(of: node.id)
        let path = graph.learningPath(to: node.id)

        ZStack(alignment: .bottom) {
            GRColor.canvas.ignoresSafeArea()
            GRBackdropGlow(tint: nodeColor, offset: CGSize(width: 150, height: -260))

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    topBar
                    hero(neighborCount: neighbors.count)
                    masteryCard
                    definitionCard
                    if path.count > 1 { pathCard(path) }
                    if !neighbors.isEmpty { connections(neighbors) }
                    if !cards.isEmpty { cardsSection }
                    if !resources.isEmpty { sourcesSection }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 120)
            }

            actionBar
        }
        .preferredColorScheme(.dark)
        .task(id: node.id) { await load() }
        .sheet(isPresented: $showQuiz) {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                GraphQuizSheet(topic: node.name, isDemo: graph.usingStub, onClose: { showQuiz = false })
                    .padding(16)
            }
            .presentationDetents([.medium, .large])
            .preferredColorScheme(.dark)
        }
    }

    private var topBar: some View {
        HStack(spacing: 8) {
            GRIconButton(systemImage: "chevron.down", tint: GRColor.textPrimary, accessibilityLabel: "Close") {
                dismiss()
            }
            Spacer()
            GRIconButton(systemImage: "point.3.connected.trianglepath.dotted", accessibilityLabel: "Show in graph") {
                graph.select(nodeId: node.id)
                dismiss()
            }
            ShareLink(item: "\(node.name) — \(definition)") {
                Image(systemName: "square.and.arrow.up")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(GRColor.textPrimary)
                    .frame(width: 40, height: 40)
                    .grGlassEffect(.interactive, in: Circle())
            }
            .accessibilityLabel("Share concept")
        }
        .padding(.top, 16)
    }

    private func hero(neighborCount: Int) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Circle().fill(nodeColor).frame(width: 12, height: 12)
                Text(node.name)
                    .font(GRType.largeTitle)
                    .foregroundStyle(GRColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            GRFlowLayout {
                if let domain = focus?.center.domain ?? node.domain, !domain.isEmpty {
                    GRChip(title: domain, style: .tinted(.cyan), compact: true)
                }
                if let community = graph.graph.communities.first(where: { $0.entityIds.contains(node.id) }) {
                    GRChip(title: community.title ?? community.label ?? "Community", compact: true)
                }
                GRChip(title: "\(focus?.totalConnections ?? neighborCount) links", compact: true)
            }
        }
    }

    private var masteryCard: some View {
        GlassCard {
            HStack(spacing: 16) {
                GRProgressRing(progress: mastery, lineWidth: 7, tint: isWeak ? GRColor.amber : GRColor.accent) {
                    Text("\(Int((mastery * 100).rounded()))%")
                        .font(GRType.caption.weight(.bold))
                        .foregroundStyle(GRColor.textPrimary)
                }
                .frame(width: 64, height: 64)
                VStack(alignment: .leading, spacing: 3) {
                    Text(masteryTitle)
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Text("\(cards.count) card\(cards.count == 1 ? "" : "s") · \(graph.prerequisites(of: node.id).count) prerequisites")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
                Spacer(minLength: 0)
            }
        }
    }

    private var masteryTitle: String {
        switch mastery {
        case ..<0.01: return "Not reviewed yet"
        case ..<0.4: return "Needs work"
        case ..<0.75: return "Getting there"
        default: return "Strong"
        }
    }

    private var definitionCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                Text("DEFINITION")
                    .font(GRType.micro)
                    .tracking(0.6)
                    .foregroundStyle(GRColor.textTertiary)
                Text(definition)
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textPrimary)
                    .textSelection(.enabled)
            }
        }
    }

    private func pathCard(_ path: [GraphNode]) -> some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 0) {
                Label("Learning path", systemImage: "point.topleft.down.to.point.bottomright.curvepath")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                    .padding(.bottom, 12)
                ForEach(Array(path.enumerated()), id: \.element.id) { index, step in
                    let isCurrent = step.id == node.id
                    let mastered = (step.masteryLevel ?? 0) >= 0.6
                    HStack(alignment: .top, spacing: 12) {
                        VStack(spacing: 0) {
                            ZStack {
                                if isCurrent {
                                    Circle().fill(GRColor.accent)
                                } else if mastered {
                                    Circle().fill(GRColor.accentSoft)
                                    Image(systemName: "checkmark")
                                        .font(.system(size: 10, weight: .heavy))
                                        .foregroundStyle(GRColor.accent)
                                } else {
                                    Circle().stroke(GRColor.strokeStrong, lineWidth: 1.5)
                                }
                            }
                            .frame(width: 22, height: 22)
                            if index < path.count - 1 {
                                Rectangle()
                                    .fill(mastered || isCurrent ? GRColor.accent.opacity(0.6) : GRColor.fillMuted)
                                    .frame(width: 2, height: 20)
                            }
                        }
                        Button {
                            if !isCurrent { graph.detailNode = step }
                        } label: {
                            Text(step.name)
                                .font(isCurrent ? GRType.headline : GRType.caption)
                                .foregroundStyle(isCurrent ? GRColor.accent : (mastered ? GRColor.textSecondary : GRColor.textTertiary))
                                .padding(.top, isCurrent ? 1 : 3)
                        }
                        .buttonStyle(.plain)
                        .disabled(isCurrent)
                        if isCurrent {
                            GRChip(title: "You are here", style: .tinted(.accent), compact: true)
                        }
                        Spacer(minLength: 0)
                    }
                }
            }
        }
    }

    private func connections(_ neighbors: [(node: GraphNode, relationship: String)]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Connections")
            GRFlowLayout(spacing: 6, lineSpacing: 6) {
                ForEach(neighbors.prefix(14), id: \.node.id) { item in
                    Button {
                        graph.detailNode = item.node
                    } label: {
                        HStack(spacing: 6) {
                            Circle()
                                .fill(GraphInspectorPanel.relColors[item.relationship] ?? .white)
                                .frame(width: 7, height: 7)
                            Text(item.node.name)
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textPrimary)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 7)
                        .background(Capsule().fill(GRColor.fillSubtle))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var cardsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Cards · \(cards.count)", actionTitle: "Quiz me") { showQuiz = true }
            ForEach(cards.prefix(3)) { card in
                GRListRow(
                    title: card.displayQuestion,
                    subtitle: (card.questionType ?? "card").replacingOccurrences(of: "_", with: " ").capitalized,
                    systemImage: "checklist",
                    tone: .purple,
                    showsChevron: false
                )
            }
        }
    }

    private var sourcesSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Sources")
            ForEach(resources.prefix(4)) { resource in
                let row = GRListRow(
                    title: resource.title,
                    subtitle: resource.resourceType?.capitalized ?? resource.type?.capitalized,
                    systemImage: resource.sourceURL?.contains("youtu") == true ? "play.rectangle.fill" : "doc.text.fill",
                    tone: .coral,
                    showsChevron: resource.sourceURL != nil
                )
                if let raw = resource.sourceURL, let url = URL(string: raw) {
                    Link(destination: url) { row }
                } else {
                    row
                }
            }
        }
    }

    private var actionBar: some View {
        HStack(spacing: 10) {
            Button { showQuiz = true } label: { Label("Quiz me", systemImage: "target") }
                .buttonStyle(.grPrimary)
            Button {
                router.ask("Explain \(node.name) and how it connects to what I already know.", topic: node.name)
                dismiss()
            } label: {
                Label("Ask", systemImage: "sparkles")
            }
            .buttonStyle(.grSecondary)
        }
        .padding(10)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .padding(.horizontal, 20)
        .padding(.bottom, 8)
    }

    private func load() async {
        guard !graph.usingStub else { return }
        async let focusResult = try? APIClient.shared.focusConcept(id: node.id)
        async let resourceResult = try? APIClient.shared.fetchConceptResources(conceptName: node.name)
        async let quizResult = try? APIClient.shared.fetchQuizHistory()
        focus = await focusResult
        resources = await resourceResult?.resources ?? []
        let quizzes = await quizResult?.quizzes ?? []
        cards = quizzes.filter {
            $0.conceptId == node.id || $0.topic?.caseInsensitiveCompare(node.name) == .orderedSame
        }
    }
}
