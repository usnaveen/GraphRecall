import SwiftUI

/// Card for the selected concept. Compact by default — what it is, mastery and connections — so the
/// graph stays usable; the expand button reveals the full card, capped to part of the canvas.
struct GraphInspectorPanel: View {
    let node: GraphNode
    let model: GraphViewModel
    /// Tallest the expanded card may grow; the graph keeps the rest of the canvas.
    var maxExpandedHeight: CGFloat
    var onAsk: () -> Void

    static let parentTint = Color(hex: "#3B82F6") ?? .blue
    static let childTint = Color(hex: "#10B981") ?? .green

    private var nodeColor: Color { Color(hex: node.color ?? "#B6FF2E") ?? GRColor.accent }
    private var community: GraphCommunity? { model.community(containing: node.id) }
    private var mastery: Double { node.masteryLevel ?? 0 }
    private var masteryTint: Color {
        if mastery <= 0 { return GRColor.textTertiary }
        return mastery < GraphViewModel.weakThreshold ? GRColor.amber : GRColor.accent
    }
    private var masteryLabel: String {
        mastery > 0 ? "Mastery \(Int((mastery * 100).rounded()))%" : "Not reviewed yet"
    }

    var body: some View {
        let neighbors = model.neighbors(of: node.id)

        VStack(alignment: .leading, spacing: 10) {
            header(connectionCount: neighbors.count)
            if model.cardExpanded {
                expandedContent(neighbors: neighbors)
                    .transition(.opacity)
            } else {
                compactContent(connectionCount: neighbors.count)
                    .transition(.opacity)
            }
        }
        .padding(14)
        .frame(maxHeight: model.cardExpanded ? maxExpandedHeight : nil, alignment: .top)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous).stroke(GRColor.strokeStrong, lineWidth: 1))
    }

    // MARK: - Header

    private func header(connectionCount: Int) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Circle()
                .fill(nodeColor)
                .frame(width: 10, height: 10)
                .padding(.top, 6)
            VStack(alignment: .leading, spacing: 2) {
                Text(node.name)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                    .lineLimit(model.cardExpanded ? 3 : 2)
                Text(subtitle(connectionCount: connectionCount))
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textTertiary)
                    .lineLimit(1)
            }
            Spacer(minLength: 6)
            HStack(spacing: 2) {
                GRIconButton(systemImage: "target", style: .plain, tint: GRColor.accent, size: 34, accessibilityLabel: "Quiz me on \(node.name)") {
                    model.openQuiz()
                }
                GRIconButton(
                    systemImage: model.cardExpanded ? "arrow.down.right.and.arrow.up.left" : "arrow.up.left.and.arrow.down.right",
                    style: .plain,
                    size: 34,
                    accessibilityLabel: model.cardExpanded ? "Collapse card" : "Expand card"
                ) {
                    withAnimation(.snappy(duration: 0.3)) { model.cardExpanded.toggle() }
                }
                GRIconButton(systemImage: "xmark", style: .plain, size: 34, accessibilityLabel: "Close") {
                    withAnimation(.easeInOut(duration: 0.22)) { model.select(nodeId: nil) }
                }
            }
        }
    }

    private func subtitle(connectionCount: Int) -> String {
        if let domain = node.domain, !domain.isEmpty { return domain }
        return community?.title ?? community?.label ?? "Concept"
    }

    // MARK: - Compact

    private func compactContent(connectionCount: Int) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if let definition = node.definition, !definition.isEmpty {
                Text(definition)
                    .font(.subheadline)
                    .foregroundStyle(GRColor.textSecondary)
                    .lineLimit(2)
            }
            HStack(spacing: 10) {
                masteryRow
                Text("\(connectionCount) link\(connectionCount == 1 ? "" : "s")")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                    .fixedSize()
            }
            // Create / merge / suggest are easy to miss if they only live in the expanded card.
            compactTools
        }
    }

    private var compactTools: some View {
        HStack(spacing: 6) {
            GRChip(title: "Suggest links", systemImage: "link.badge.plus", style: .outline, compact: true) {
                model.toolSheet = .suggestLinks
            }
            GRChip(title: "Merge…", systemImage: "arrow.triangle.merge", style: .outline, compact: true) {
                model.enterMergeMode()
            }
            Spacer(minLength: 0)
        }
    }

    private var masteryRow: some View {
        HStack(spacing: 10) {
            Text(masteryLabel)
                .font(GRType.caption.weight(.bold))
                .foregroundStyle(masteryTint)
                .fixedSize()
            GRProgressBar(value: mastery, tint: masteryTint, height: 4)
        }
    }

    // MARK: - Expanded

    private func expandedContent(neighbors: [(node: GraphNode, relationship: String)]) -> some View {
        let prerequisites = Self.unique(model.prerequisites(of: node.id))
        let unlocks = Self.unique(model.unlocks(of: node.id))

        return ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let definition = node.definition, !definition.isEmpty {
                    Text(definition)
                        .font(.subheadline)
                        .foregroundStyle(GRColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                masteryRow
                actionGrid

                if !prerequisites.isEmpty {
                    chipSection("Needs first", systemImage: "arrow.turn.left.up", nodes: prerequisites, tone: .cyan)
                }
                if !unlocks.isEmpty {
                    chipSection("Unlocks", systemImage: "arrow.turn.right.down", nodes: unlocks, tone: .accent)
                }

                toolChips
                relationshipDetails(neighbors: neighbors)
            }
            .padding(.bottom, 4)
        }
        .scrollIndicators(.hidden)
    }

    private var actionGrid: some View {
        Grid(horizontalSpacing: 8, verticalSpacing: 8) {
            GridRow {
                Button { model.openNotes() } label: {
                    Label("Notes", systemImage: "book").frame(maxWidth: .infinity)
                }
                Button { model.openLinks() } label: {
                    Label("Sources", systemImage: "link").frame(maxWidth: .infinity)
                }
            }
            GridRow {
                Button(action: onAsk) {
                    Label("Ask", systemImage: "sparkles").frame(maxWidth: .infinity)
                }
                Button { model.detailNode = node } label: {
                    Label("Details", systemImage: "doc.text.magnifyingglass").frame(maxWidth: .infinity)
                }
            }
        }
        .grButton(.secondary, compact: true)
    }

    private var toolChips: some View {
        GRFlowLayout(spacing: 6, lineSpacing: 6) {
            GRChip(title: "Suggest links", systemImage: "link.badge.plus", style: .outline, compact: true) {
                model.toolSheet = .suggestLinks
            }
            GRChip(title: "Merge…", systemImage: "arrow.triangle.merge", style: .outline, compact: true) {
                model.enterMergeMode()
            }
            if community != nil {
                GRChip(
                    title: model.isolateCommunity ? "Show all" : "Isolate community",
                    systemImage: "square.3.layers.3d",
                    style: model.isolateCommunity ? .selected : .outline,
                    compact: true
                ) {
                    model.toggleCommunityFocus()
                }
            }
        }
    }

    private func chipSection(_ title: String, systemImage: String, nodes: [GraphNode], tone: GRTone) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            sectionTitle(title, systemImage: systemImage)
            GRFlowLayout(spacing: 6, lineSpacing: 6) {
                ForEach(nodes.prefix(8)) { item in
                    GRChip(title: item.name, style: .tinted(tone), compact: true) {
                        model.select(nodeId: item.id)
                    }
                }
            }
        }
    }

    private static func unique(_ nodes: [GraphNode]) -> [GraphNode] {
        var seen = Set<String>()
        return nodes.filter { seen.insert($0.id).inserted }
    }

    // MARK: - Relationships

    @ViewBuilder
    private func relationshipDetails(neighbors: [(node: GraphNode, relationship: String)]) -> some View {
        HStack(spacing: 6) {
            badge("\(neighbors.count) connection\(neighbors.count == 1 ? "" : "s")")
            if let domain = node.domain, !domain.isEmpty { badge(domain) }
            if let level = community?.level { badge("Level \(level)") }
        }

        if let hierarchy = model.communityHierarchy(for: node.id) {
            VStack(alignment: .leading, spacing: 6) {
                sectionTitle("Community hierarchy", systemImage: "square.3.layers.3d")
                ForEach(hierarchy.parents) { hierarchyRow("PARENT", $0, tint: Self.parentTint) }
                hierarchyRow("CURRENT", hierarchy.current, tint: GRColor.accent)
                ForEach(hierarchy.children) { hierarchyRow("CHILD", $0, tint: Self.childTint) }
            }
        }

        let strongest = model.strongestRelationships(of: node.id)
        if !strongest.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                sectionTitle("Strongest relationships", systemImage: "point.3.connected.trianglepath.dotted")
                ForEach(strongest, id: \.edge.id) { item in
                    strongestRow(edge: item.edge, other: item.node)
                }
            }
        }

        if !neighbors.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                sectionTitle("Connected concepts (\(neighbors.count))", systemImage: "circle.hexagongrid")
                GRFlowLayout(spacing: 6, lineSpacing: 6) {
                    ForEach(neighbors, id: \.node.id) { item in
                        Button {
                            model.select(nodeId: item.node.id)
                        } label: {
                            HStack(spacing: 5) {
                                Circle()
                                    .fill(GraphRelationshipStyle.color(item.relationship))
                                    .frame(width: 6, height: 6)
                                Text(item.node.name)
                                    .font(GRType.micro)
                                    .foregroundStyle(GRColor.textSecondary)
                                    .lineLimit(1)
                            }
                        }
                        .buttonStyle(.glass)
                        .buttonBorderShape(.capsule)
                        .controlSize(.mini)
                    }
                }
            }
        }
    }

    private func badge(_ text: String) -> some View {
        Text(text)
            .font(GRType.micro)
            .foregroundStyle(GRColor.textSecondary)
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Capsule().fill(GRColor.fillMuted))
    }

    private func sectionTitle(_ title: String, systemImage: String) -> some View {
        Label(title.uppercased(), systemImage: systemImage)
            .font(.system(size: 9, weight: .semibold, design: .rounded))
            .tracking(0.6)
            .foregroundStyle(GRColor.textTertiary)
    }

    private func hierarchyRow(_ tag: String, _ community: GraphCommunity, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(tag)
                    .font(.system(size: 9, weight: .bold, design: .rounded))
                    .foregroundStyle(tint)
                if let level = community.level {
                    Text("L\(level)")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                }
                Text("\(community.size ?? community.entityIds.count) concepts")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
            }
            Text(community.title ?? community.label ?? "Community")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textPrimary)
                .lineLimit(1)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(tint.opacity(0.06), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(tint.opacity(0.28), lineWidth: 1))
    }

    private func strongestRow(edge: GraphEdge, other: GraphNode) -> some View {
        let relationship = (edge.relationshipType ?? "RELATED_TO").uppercased()
        let tint = GraphRelationshipStyle.color(relationship)
        return Button {
            model.select(nodeId: other.id)
        } label: {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Circle().fill(tint).frame(width: 6, height: 6)
                    Text(other.name)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textPrimary)
                        .lineLimit(1)
                    Spacer(minLength: 6)
                    Text("\(Int(((edge.strength ?? 0.6) * 100).rounded()))%")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                }
                Text(relationship.replacingOccurrences(of: "_", with: " "))
                    .font(.system(size: 9, weight: .medium, design: .rounded))
                    .foregroundStyle(tint.opacity(0.8))
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
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
