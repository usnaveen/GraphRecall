import SwiftUI

/// Liquid Glass inspector for the selected concept — mastery, prerequisites and actions.
struct GraphInspectorPanel: View {
    let node: GraphNode
    let model: GraphViewModel
    var onAsk: () -> Void

    @State private var showConnections = false

    static let relColors: [String: Color] = [
        "PREREQUISITE_OF": Color(hex: "#2EFFE6") ?? .cyan,
        "SUBTOPIC_OF": Color(hex: "#9B59B6") ?? .purple,
        "BUILDS_ON": Color(hex: "#F59E0B") ?? .orange,
        "RELATED_TO": .white,
        "PART_OF": Color(hex: "#EC4899") ?? .pink,
        "USES": Color(hex: "#3B82F6") ?? .blue,
        "ORCHESTRATED_BY": Color(hex: "#7C3AED") ?? .purple,
        "SUPPORTS": Color(hex: "#10B981") ?? .green,
    ]

    private var nodeColor: Color { Color(hex: node.color ?? "#B6FF2E") ?? GRColor.accent }
    private var community: GraphCommunity? { model.graph.communities.first { $0.entityIds.contains(node.id) } }
    private var mastery: Double { node.masteryLevel ?? 0 }
    private var isWeak: Bool { mastery < GraphViewModel.weakThreshold }

    var body: some View {
        let neighbors = model.neighbors(of: node.id)
        let prerequisites = model.prerequisites(of: node.id)

        VStack(alignment: .leading, spacing: 12) {
            header

            if let definition = node.definition, !definition.isEmpty {
                Text(definition)
                    .font(.subheadline)
                    .foregroundStyle(GRColor.textSecondary)
                    .lineLimit(3)
            }

            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(mastery > 0 ? "Mastery \(Int((mastery * 100).rounded()))%" : "Not reviewed yet")
                        .font(GRType.caption.weight(.bold))
                        .foregroundStyle(isWeak ? GRColor.amber : GRColor.accent)
                    Spacer()
                    Text("\(neighbors.count) connection\(neighbors.count == 1 ? "" : "s")")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                }
                GRProgressBar(value: mastery, tint: isWeak ? GRColor.amber : GRColor.accent)
            }

            if !prerequisites.isEmpty {
                HStack(spacing: 8) {
                    Text("Needs")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            ForEach(prerequisites.prefix(6)) { prereq in
                                GRChip(title: prereq.name, style: .tinted(.cyan), compact: true) {
                                    model.select(nodeId: prereq.id)
                                }
                            }
                        }
                    }
                }
            }

            if showConnections && !neighbors.isEmpty {
                GRFlowLayout(spacing: 6, lineSpacing: 6) {
                    ForEach(neighbors.prefix(12), id: \.node.id) { item in
                        Button {
                            model.select(nodeId: item.node.id)
                        } label: {
                            HStack(spacing: 5) {
                                Circle()
                                    .fill(Self.relColors[item.relationship] ?? .white)
                                    .frame(width: 6, height: 6)
                                Text(item.node.name)
                                    .font(GRType.micro)
                                    .foregroundStyle(GRColor.textSecondary)
                                    .lineLimit(1)
                            }
                            .padding(.horizontal, 9)
                            .padding(.vertical, 5)
                            .background(Capsule().fill(GRColor.fillSubtle))
                        }
                        .buttonStyle(.plain)
                    }
                }
                .transition(.opacity)
            }

            HStack(spacing: 8) {
                Button { model.openQuiz() } label: { Label("Quiz me", systemImage: "target") }
                    .buttonStyle(GRButtonStyle(kind: .primary, compact: true))
                Button { model.openNotes() } label: { Label("Notes", systemImage: "book") }
                    .buttonStyle(GRButtonStyle(kind: .secondary, compact: true))
                Button { model.detailNode = node } label: { Label("Details", systemImage: "arrow.up.left.and.arrow.down.right") }
                    .buttonStyle(GRButtonStyle(kind: .secondary, compact: true))
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    GRChip(title: "Ask", systemImage: "sparkles", style: .outline, compact: true, action: onAsk)
                    GRChip(title: "Suggest links", systemImage: "link.badge.plus", style: .outline, compact: true) {
                        model.toolSheet = .suggestLinks
                    }
                    GRChip(title: "Merge…", systemImage: "arrow.triangle.merge", style: .outline, compact: true) {
                        model.toolSheet = .merge
                    }
                    GRChip(title: "Sources", systemImage: "link", style: .outline, compact: true) {
                        model.openLinks()
                    }
                    if !neighbors.isEmpty {
                        GRChip(
                            title: showConnections ? "Hide connections" : "Connections",
                            systemImage: showConnections ? "chevron.up" : "chevron.down",
                            style: .outline,
                            compact: true
                        ) {
                            withAnimation(.easeInOut(duration: 0.2)) { showConnections.toggle() }
                        }
                    }
                }
            }

            if model.isRecomputingCommunities {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.mini).tint(GRColor.accent)
                    Text("Recomputing communities…")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                }
            }
        }
        .padding(16)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 24, style: .continuous).stroke(GRColor.strokeStrong, lineWidth: 1))
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 10) {
            Circle()
                .fill(nodeColor)
                .frame(width: 10, height: 10)
                .padding(.top, 8)
            VStack(alignment: .leading, spacing: 2) {
                Text(node.name)
                    .font(GRType.title)
                    .foregroundStyle(GRColor.textPrimary)
                    .lineLimit(2)
                Text(subtitle)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textTertiary)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            if community != nil {
                GRIconButton(
                    systemImage: "square.3.layers.3d",
                    style: .plain,
                    tint: model.isolateCommunity ? GRColor.accent : GRColor.textSecondary,
                    size: 32,
                    accessibilityLabel: model.isolateCommunity ? "Show all" : "Isolate community"
                ) {
                    model.toggleCommunityFocus()
                }
            }
            GRIconButton(systemImage: "xmark", style: .plain, size: 32, accessibilityLabel: "Close inspector") {
                model.select(nodeId: nil)
            }
        }
    }

    private var subtitle: String {
        var parts: [String] = []
        if let community {
            parts.append("\(community.title ?? community.label ?? "Community") · \(community.size ?? community.entityIds.count) nodes")
        } else if let domain = node.domain, !domain.isEmpty {
            parts.append(domain)
        }
        if let level = community?.level { parts.append("Level \(level)") }
        return parts.joined(separator: " · ")
    }
}

extension Color {
    init?(hex: String) {
        var s = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6 || s.count == 8 else { return nil }
        var value: UInt64 = 0
        guard Scanner(string: s).scanHexInt64(&value) else { return nil }
        let hasAlpha = s.count == 8
        let a = hasAlpha ? Double((value & 0xFF000000) >> 24) / 255 : 1
        let r = Double((value & 0x00FF0000) >> 16) / 255
        let g = Double((value & 0x0000FF00) >> 8) / 255
        let b = Double(value & 0x000000FF) / 255
        self.init(.sRGB, red: r, green: g, blue: b, opacity: a)
    }
}
