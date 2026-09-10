import SwiftUI

struct GraphView: View {
    @State private var model = GraphViewModel()

    var body: some View {
        VStack(spacing: 0) {
            header
            searchBar
            ZStack(alignment: .bottom) {
                GraphForceWebView(
                    graph: model.graph,
                    highlightIds: highlightSet,
                    onSelect: { id in model.select(nodeId: id) }
                )
                .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                .padding(.horizontal, 16)
                .padding(.top, 8)

                if model.isLoading {
                    ProgressView()
                        .tint(GRColor.accent)
                        .padding(16)
                        .grGlassEffect(in: Capsule())
                }

                detailCard
                    .padding(.horizontal, 20)
                    .padding(.bottom, 12)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .padding(.bottom, 88)
        .task { await model.load() }
    }

    private var highlightSet: Set<String> {
        let q = model.searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        if !q.isEmpty {
            return Set(model.filteredNodes.map(\.id))
        }
        if let id = model.selectedNodeId { return [id] }
        return []
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Graph")
                    .font(GRType.largeTitle)
                    .foregroundStyle(GRColor.textPrimary)
                Text(model.usingStub ? "Demo graph · API unreachable" : model.statsLabel)
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)
            }
            Spacer()
            Button {
                Task { await model.load() }
            } label: {
                Image(systemName: "arrow.clockwise")
                    .foregroundStyle(GRColor.accent)
                    .padding(10)
                    .grGlassEffect(.interactive, in: Circle())
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 20)
        .padding(.bottom, 8)
    }

    private var searchBar: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(GRColor.textTertiary)
            TextField("Find concept…", text: $model.searchQuery)
                .textInputAutocapitalization(.never)
                .disableAutocorrection(true)
                .foregroundStyle(GRColor.textPrimary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .grGlassEffect(.interactive, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .padding(.horizontal, 20)
    }

    @ViewBuilder
    private var detailCard: some View {
        if let node = model.selectedNode {
            GlassCard(cornerRadius: 18) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Circle()
                            .fill(Color(hex: node.color ?? "#B6FF2E") ?? GRColor.accent)
                            .frame(width: 10, height: 10)
                        Text(node.name)
                            .font(GRType.headline)
                            .foregroundStyle(GRColor.textPrimary)
                        Spacer()
                        if let domain = node.domain {
                            Text(domain)
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textSecondary)
                        }
                    }
                    if let definition = node.definition, !definition.isEmpty {
                        Text(definition)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textSecondary)
                            .lineLimit(3)
                    }
                    if let err = model.errorMessage, model.usingStub {
                        Text(err)
                            .font(GRType.micro)
                            .foregroundStyle(Color.orange)
                            .lineLimit(2)
                    }
                }
            }
        }
    }
}

private extension Color {
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

#Preview {
    ZStack {
        GRColor.canvas.ignoresSafeArea()
        GraphView()
    }
    .preferredColorScheme(.dark)
}
