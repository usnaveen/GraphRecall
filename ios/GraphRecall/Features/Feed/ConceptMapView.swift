import SwiftUI

/// Where a concept sits in the user's own knowledge graph (`content["concept_map"]`, built by
/// backend/services/concept_maps.py): what it is part of, what it needs, what it unlocks, what it
/// includes, and what it relates to. Every concept card can show this, unlike source figures.
struct ConceptMap: Equatable, Sendable {
    struct Node: Equatable, Sendable, Identifiable {
        let name: String
        let role: ConceptRole
        var id: String { name }
    }

    let center: String
    let nodes: [Node]
}

enum ConceptRole: String, CaseIterable, Sendable {
    case partOf = "part_of", needs, unlocks, includes, related

    var label: String {
        switch self {
        case .partOf: return "part of"
        case .needs: return "needs"
        case .unlocks: return "unlocks"
        case .includes: return "includes"
        case .related: return "related"
        }
    }

    var color: Color {
        switch self {
        case .partOf: return GRColor.purple
        case .needs: return GRColor.amber
        case .unlocks: return GRColor.accentCyan
        case .includes: return GRColor.accent
        case .related: return GRColor.textSecondary
        }
    }

    /// Screen angle in degrees (0 = right, 90 = down): parent above, contents below,
    /// prerequisites to the left, what it unlocks to the right, related on the diagonals.
    var baseAngle: Double {
        switch self {
        case .partOf: return -90
        case .includes: return 90
        case .needs: return 180
        case .unlocks: return 0
        case .related: return -40
        }
    }
}

extension FeedItem {
    var conceptMap: ConceptMap? {
        guard let raw = content["concept_map"]?.value as? [String: Any],
              let center = raw["center"] as? String, !center.isEmpty,
              let list = raw["nodes"] as? [Any] else { return nil }
        let nodes: [ConceptMap.Node] = list.compactMap { el in
            guard let d = el as? [String: Any], let name = d["name"] as? String, !name.isEmpty else { return nil }
            return ConceptMap.Node(name: name, role: ConceptRole(rawValue: d["role"] as? String ?? "") ?? .related)
        }
        return nodes.isEmpty ? nil : ConceptMap(center: center, nodes: nodes)
    }

    /// The picture for a concept card: a figure from the user's sources when one is about this
    /// concept, otherwise the concept's place in their graph.
    var hasConceptVisual: Bool { conceptFigure != nil || conceptMap != nil }
}

/// The figure if there is one, else the graph picture.
struct ConceptVisual: View {
    let item: FeedItem

    var body: some View {
        if let figure = item.conceptFigure {
            ConceptFigureView(figure: figure)
                .id(figure.id)
        } else if let map = item.conceptMap {
            ConceptMapView(map: map)
                .id(item.id)
        }
    }
}

/// The concept with its neighbours laid out by meaning rather than scattered: what it is part of
/// above, what it needs on the left, what it unlocks on the right, what it includes below, and
/// related concepts as dashed chips. Nothing can overlap, and each group says what it is.
struct ConceptMapView: View {
    let map: ConceptMap

    @State private var appeared = false

    private func nodes(_ role: ConceptRole) -> [ConceptMap.Node] {
        map.nodes.filter { $0.role == role }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("WHERE IT SITS IN YOUR GRAPH")
                .font(GRType.micro)
                .foregroundStyle(GRColor.textTertiary)

            VStack(spacing: 4) {
                if let parent = nodes(.partOf).first {
                    group(.partOf, [parent], index: 0)
                    connector(.partOf, vertical: true, index: 0)
                }

                HStack(alignment: .center, spacing: 4) {
                    sideColumn(.needs, index: 1)
                    if !nodes(.needs).isEmpty { connector(.needs, vertical: false, index: 1) }
                    centerNode
                    if !nodes(.unlocks).isEmpty { connector(.unlocks, vertical: false, index: 2) }
                    sideColumn(.unlocks, index: 2)
                }

                if !nodes(.includes).isEmpty {
                    connector(.includes, vertical: true, index: 3)
                    group(.includes, nodes(.includes), index: 3)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .padding(.horizontal, 8)
            .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 18, style: .continuous))

            if !nodes(.related).isEmpty {
                HStack(spacing: 6) {
                    Text("related")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    ForEach(Array(nodes(.related).enumerated()), id: \.element.id) { i, node in
                        chip(node, dashed: true)
                            .popIn(appeared, delay: 0.35 + 0.05 * Double(i))
                    }
                }
                .lineLimit(1)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilitySummary)
        .onAppear { appeared = true }
    }

    private var centerNode: some View {
        Text(map.center)
            .font(.footnote.weight(.bold))
            .foregroundStyle(GRColor.canvas)
            .lineLimit(3)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .frame(maxWidth: 112)
            .background(GRColor.accent, in: Capsule())
            .shadow(color: GRColor.accent.opacity(0.35), radius: 10)
            .layoutPriority(1)
            .popIn(appeared, delay: 0)
    }

    @ViewBuilder
    private func sideColumn(_ role: ConceptRole, index: Int) -> some View {
        let list = nodes(role)
        if list.isEmpty {
            EmptyView() // not Color.clear: that would stretch the row to fill any height offered
        } else {
            VStack(spacing: 4) {
                Text(role.label).font(GRType.micro).foregroundStyle(role.color)
                ForEach(Array(list.enumerated()), id: \.element.id) { i, node in
                    chip(node, dashed: false)
                        .popIn(appeared, delay: 0.12 + 0.08 * Double(index) + 0.05 * Double(i))
                }
            }
            .frame(maxWidth: 92)
        }
    }

    private func group(_ role: ConceptRole, _ list: [ConceptMap.Node], index: Int) -> some View {
        VStack(spacing: 4) {
            if role == .partOf {
                Text(role.label).font(GRType.micro).foregroundStyle(role.color)
            }
            HStack(spacing: 6) {
                ForEach(Array(list.enumerated()), id: \.element.id) { i, node in
                    chip(node, dashed: false)
                        .frame(maxWidth: 140)
                        .popIn(appeared, delay: 0.12 + 0.08 * Double(index) + 0.05 * Double(i))
                }
            }
            if role == .includes {
                Text(role.label).font(GRType.micro).foregroundStyle(role.color)
            }
        }
    }

    private func chip(_ node: ConceptMap.Node, dashed: Bool) -> some View {
        Text(node.name)
            .font(GRType.caption.weight(.semibold))
            .foregroundStyle(GRColor.textPrimary)
            .lineLimit(2)
            .multilineTextAlignment(.center)
            .minimumScaleFactor(0.85)
            .padding(.horizontal, 9)
            .padding(.vertical, 5)
            .background(node.role.color.opacity(0.14), in: Capsule())
            .overlay(
                Capsule().stroke(node.role.color.opacity(0.65),
                                 style: StrokeStyle(lineWidth: 1, dash: dashed ? [3, 3] : []))
            )
    }

    private func connector(_ role: ConceptRole, vertical: Bool, index: Int) -> some View {
        Capsule()
            .fill(role.color.opacity(0.7))
            .frame(width: vertical ? 2 : 12, height: vertical ? 12 : 2)
            .scaleEffect(x: vertical ? 1 : (appeared ? 1 : 0), y: vertical ? (appeared ? 1 : 0) : 1)
            .animation(.easeOut(duration: 0.3).delay(0.08 + 0.08 * Double(index)), value: appeared)
    }

    private var accessibilitySummary: String {
        let parts = ConceptRole.allCases.compactMap { role -> String? in
            let names = nodes(role).map(\.name)
            return names.isEmpty ? nil : "\(role.label) \(names.joined(separator: ", "))"
        }
        return "\(map.center): " + parts.joined(separator: "; ")
    }
}

private extension View {
    /// Pops in with a spring, staggered by `delay`.
    func popIn(_ appeared: Bool, delay: Double) -> some View {
        scaleEffect(appeared ? 1 : 0.5)
            .opacity(appeared ? 1 : 0)
            .animation(.spring(response: 0.42, dampingFraction: 0.66).delay(delay), value: appeared)
    }
}
