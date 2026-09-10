import SwiftUI

/// Liquid Glass inspector — visual/content parity with web `Inspector.tsx`.
struct GraphInspectorPanel: View {
    let node: GraphNode
    let edges: [GraphEdge]
    let communities: [GraphCommunity]
    let nodesById: [String: GraphNode]
    var isRecomputing: Bool = false
    var onClose: () -> Void
    var onSelectNode: (String) -> Void
    var onFocusCommunity: (() -> Void)? = nil
    var isolateCommunity: Bool = false

    private static let relColors: [String: Color] = [
        "PREREQUISITE_OF": Color(hex: "#2EFFE6") ?? .cyan,
        "SUBTOPIC_OF": Color(hex: "#9B59B6") ?? .purple,
        "BUILDS_ON": Color(hex: "#F59E0B") ?? .orange,
        "RELATED_TO": .white,
        "PART_OF": Color(hex: "#EC4899") ?? .pink,
        "USES": Color(hex: "#3B82F6") ?? .blue,
        "ORCHESTRATED_BY": Color(hex: "#7C3AED") ?? .purple,
        "SUPPORTS": Color(hex: "#10B981") ?? .green,
    ]

    private var nodeColor: Color {
        Color(hex: node.color ?? "#B6FF2E") ?? GRColor.accent
    }

    private var community: GraphCommunity? {
        communities.first { $0.entityIds.contains(node.id) }
    }

    private var topRelationships: [(edge: GraphEdge, other: GraphNode, rel: String)] {
        edges.prefix(5).compactMap { edge in
            let otherId = edge.source == node.id ? edge.target : edge.source
            guard let other = nodesById[otherId] else { return nil }
            let rel = (edge.relationshipType ?? "RELATED_TO").uppercased()
            return (edge, other, rel)
        }
    }

    private var connectedEntities: [(node: GraphNode, rel: String)] {
        var map: [String: (GraphNode, String, Double)] = [:]
        for edge in edges {
            let otherId = edge.source == node.id ? edge.target : edge.source
            guard let other = nodesById[otherId] else { continue }
            let rel = (edge.relationshipType ?? "RELATED_TO").uppercased()
            let w = edge.strength ?? 0
            if let existing = map[otherId], existing.2 >= w { continue }
            map[otherId] = (other, rel, w)
        }
        return map.values
            .sorted { $0.2 > $1.2 }
            .map { ($0.0, $0.1) }
    }

    private var hierarchy: (current: GraphCommunity, parents: [GraphCommunity], children: [GraphCommunity])? {
        guard let current = community else { return nil }
        let parents = communities.filter { c in
            guard let parent = current.parent else { return false }
            return c.id == parent
        }
        let children = communities.filter { $0.parent == current.id }
        return (current, parents, children)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().overlay(GRColor.stroke)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    descriptionSection
                    if let hierarchy {
                        hierarchySection(hierarchy)
                    }
                    if !topRelationships.isEmpty {
                        relationshipsSection
                    }
                    if !connectedEntities.isEmpty {
                        connectedSection
                    }
                }
                .padding(14)
            }
            .frame(maxHeight: 280)
        }
        .background {
            inspectorChrome
        }
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .stroke(GRColor.strokeStrong, lineWidth: 1)
        )
    }

    private var inspectorChrome: some View {
        Group {
            if #available(iOS 26.0, *) {
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .fill(Color.clear)
                    .glassEffect(.regular, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            } else {
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .fill(.ultraThinMaterial)
                    .shadow(color: .black.opacity(0.4), radius: 18, y: 10)
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 8) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Circle()
                            .fill(nodeColor)
                            .frame(width: 10, height: 10)
                        Text(node.name)
                            .font(GRType.headline)
                            .foregroundStyle(GRColor.textPrimary)
                            .lineLimit(2)
                    }
                    if let community {
                        Text("\(community.title ?? community.label ?? "Community") · \(community.size ?? community.entityIds.count) nodes")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                    }
                }
                Spacer(minLength: 8)
                Button(action: onClose) {
                    Image(systemName: "xmark")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(GRColor.textSecondary)
                        .padding(8)
                        .background(Circle().fill(GRColor.fillSubtle))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Close inspector")
            }

            HStack(spacing: 6) {
                badge("\(edges.count) connections")
                if let domain = node.domain, !domain.isEmpty {
                    badge(domain)
                }
                if let level = community?.level {
                    badge("Level \(level)")
                }
                if let mastery = node.masteryLevel {
                    badge(String(format: "Mastery %.0f%%", mastery * 100))
                }
            }

            HStack(spacing: 8) {
                if community != nil, let onFocusCommunity {
                    Button(action: onFocusCommunity) {
                        Label(
                            isolateCommunity ? "Unfocus Community" : "Focus Community",
                            systemImage: "square.3.layers.3d"
                        )
                        .font(GRType.micro)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                        .foregroundStyle(isolateCommunity ? Color(hex: "#C084FC") ?? .purple : GRColor.textSecondary)
                        .background(
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .fill(isolateCommunity ? Color.purple.opacity(0.2) : GRColor.fillSubtle)
                        )
                    }
                    .buttonStyle(.plain)
                }
                softAction(title: "Quiz", systemImage: "target", accent: true)
                softAction(title: "Notes", systemImage: "book")
                softAction(title: "Links", systemImage: "link")
            }

            if isRecomputing {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.mini).tint(GRColor.accent)
                    Text("Recomputing communities…")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                }
            }
        }
        .padding(14)
    }

    private var descriptionSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("DESCRIPTION")
                .font(GRType.micro)
                .foregroundStyle(GRColor.textTertiary)
                .tracking(0.6)
            Text(node.definition?.isEmpty == false ? (node.definition ?? "") : "No description available")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
                .lineLimit(4)
        }
    }

    private func hierarchySection(
        _ info: (current: GraphCommunity, parents: [GraphCommunity], children: [GraphCommunity])
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label {
                Text("COMMUNITY HIERARCHY")
                    .font(GRType.micro)
                    .tracking(0.6)
            } icon: {
                Image(systemName: "square.3.layers.3d")
                    .font(.system(size: 10))
            }
            .foregroundStyle(GRColor.textTertiary)

            ForEach(info.parents) { c in
                hierarchyRow(c, tag: "PARENT", tagColor: Color(hex: "#60A5FA") ?? .blue, border: Color.blue.opacity(0.25), fill: Color.blue.opacity(0.08))
            }
            hierarchyRow(
                info.current,
                tag: "CURRENT",
                tagColor: GRColor.accent,
                border: GRColor.accent.opacity(0.35),
                fill: GRColor.accent.opacity(0.08)
            )
            ForEach(info.children) { c in
                hierarchyRow(c, tag: "CHILD", tagColor: Color(hex: "#4ADE80") ?? .green, border: Color.green.opacity(0.25), fill: Color.green.opacity(0.08))
            }
        }
    }

    private func hierarchyRow(
        _ c: GraphCommunity,
        tag: String,
        tagColor: Color,
        border: Color,
        fill: Color
    ) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(tag)
                    .font(GRType.micro)
                    .foregroundStyle(tagColor)
                if let level = c.level {
                    Text("L\(level)")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                }
                Text("\(c.size ?? c.entityIds.count) entities")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
            }
            Text(c.title ?? c.label ?? c.id)
                .font(GRType.caption)
                .foregroundStyle(GRColor.textPrimary.opacity(0.85))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(fill)
                .overlay(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .stroke(border, lineWidth: 1)
                )
        )
    }

    private var relationshipsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label {
                Text("STRONGEST RELATIONSHIPS")
                    .font(GRType.micro)
                    .tracking(0.6)
            } icon: {
                Image(systemName: "arrow.triangle.branch")
                    .font(.system(size: 10))
            }
            .foregroundStyle(GRColor.textTertiary)

            ForEach(topRelationships, id: \.edge.id) { item in
                Button {
                    onSelectNode(item.other.id)
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Circle()
                                .fill(Self.relColors[item.rel] ?? .white)
                                .frame(width: 6, height: 6)
                            Text(item.other.name)
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textPrimary.opacity(0.85))
                                .lineLimit(1)
                            Spacer()
                            Text("\(Int(((item.edge.strength ?? 0.5) * 100).rounded()))%")
                                .font(GRType.micro)
                                .foregroundStyle(GRColor.textTertiary)
                        }
                        Text(item.rel.replacingOccurrences(of: "_", with: " "))
                            .font(GRType.micro)
                            .foregroundStyle(Self.relColors[item.rel] ?? GRColor.textTertiary)
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(GRColor.fillSubtle)
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var connectedSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("CONNECTED ENTITIES (\(connectedEntities.count))")
                .font(GRType.micro)
                .foregroundStyle(GRColor.textTertiary)
                .tracking(0.6)

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 72), spacing: 6)], alignment: .leading, spacing: 6) {
                ForEach(connectedEntities, id: \.node.id) { item in
                    Button {
                        onSelectNode(item.node.id)
                    } label: {
                        HStack(spacing: 4) {
                            Circle()
                                .fill(Self.relColors[item.rel] ?? .white)
                                .frame(width: 4, height: 4)
                            Text(item.node.name)
                                .font(GRType.micro)
                                .foregroundStyle(GRColor.textSecondary)
                                .lineLimit(1)
                        }
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .frame(maxWidth: .infinity)
                        .background(
                            Capsule()
                                .fill(GRColor.fillSubtle)
                                .overlay(Capsule().stroke(GRColor.stroke, lineWidth: 1))
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func badge(_ text: String) -> some View {
        Text(text)
            .font(GRType.micro)
            .foregroundStyle(GRColor.textSecondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Capsule().fill(GRColor.fillSubtle))
    }

    private func softAction(title: String, systemImage: String, accent: Bool = false) -> some View {
        Label(title, systemImage: systemImage)
            .font(GRType.micro)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
            .foregroundStyle(accent ? GRColor.accent : GRColor.textSecondary)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(accent ? GRColor.accent.opacity(0.18) : GRColor.fillSubtle)
            )
            .opacity(0.85)
            .accessibilityLabel("\(title) (coming soon)")
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
