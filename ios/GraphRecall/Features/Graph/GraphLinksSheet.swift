import SwiftUI

/// Inspector Links — opens related URLs from `GET /api/feed/resources/{name}`.
struct GraphLinksSheet: View {
    let conceptName: String
    var isDemo: Bool = false
    var onClose: () -> Void

    @Environment(\.openURL) private var openURL
    @State private var resources: [ConceptResource] = []
    @State private var isLoading = true
    @State private var errorMessage: String?

    private var linkResources: [ConceptResource] {
        resources.filter { r in
            let rt = (r.resourceType ?? "").lowercased()
            let hasURL = !(r.sourceURL ?? "").isEmpty
            return hasURL || ["article", "youtube", "documentation", "url", "web"].contains(rt)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(GRColor.stroke)
            content
        }
        .background {
            if #available(iOS 26.0, *) {
                Color.clear.glassEffect(.regular, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            } else {
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .fill(.ultraThinMaterial)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .stroke(GRColor.strokeStrong, lineWidth: 1)
        )
        .task(id: conceptName) { await load() }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "link")
                .foregroundStyle(GRColor.accentCyan)
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 2) {
                Text("Links: \(conceptName)")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                    .lineLimit(2)
                Text(isLoading ? "Loading…" : "\(linkResources.count) related URL\(linkResources.count == 1 ? "" : "s")")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
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
            .accessibilityLabel("Close links")
        }
        .padding(14)
    }

    @ViewBuilder
    private var content: some View {
        if isLoading {
            HStack(spacing: 10) {
                ProgressView().tint(GRColor.accent)
                Text("Finding related links…")
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textSecondary)
            }
            .frame(maxWidth: .infinity)
            .padding(28)
        } else if let errorMessage {
            Text(errorMessage)
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
                .multilineTextAlignment(.center)
                .padding(24)
                .frame(maxWidth: .infinity)
        } else if linkResources.isEmpty {
            VStack(spacing: 8) {
                Image(systemName: "link.badge.plus")
                    .font(.system(size: 28))
                    .foregroundStyle(GRColor.textTertiary)
                Text("No links found")
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textSecondary)
                Text("Ingest articles / YouTube / docs that mention this concept")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                    .multilineTextAlignment(.center)
            }
            .padding(28)
            .frame(maxWidth: .infinity)
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 10) {
                    ForEach(linkResources) { res in
                        linkRow(res)
                    }
                }
                .padding(14)
            }
            .frame(maxHeight: 320)
        }
    }

    private func linkRow(_ res: ConceptResource) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                Text(res.title)
                    .font(GRType.caption.weight(.medium))
                    .foregroundStyle(GRColor.textPrimary)
                    .lineLimit(2)
                Spacer()
                if let rt = res.resourceType, !rt.isEmpty {
                    Text(rt)
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                }
            }
            if let preview = res.preview, !preview.isEmpty {
                Text(preview)
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textSecondary)
                    .lineLimit(3)
            }
            if let raw = res.sourceURL, let url = URL(string: raw) {
                Button {
                    openURL(url)
                } label: {
                    Label("Open link", systemImage: "arrow.up.right.square")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.accentCyan)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(GRColor.fillSubtle)
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(GRColor.stroke, lineWidth: 1)
                )
        )
    }

    private func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        if isDemo {
            resources = demoResources()
            return
        }

        do {
            let response = try await APIClient.shared.fetchConceptResources(conceptName: conceptName)
            resources = response.resources
        } catch {
            errorMessage = APIError.userFacing(error, resource: "links")
            resources = []
        }
    }

    private func demoResources() -> [ConceptResource] {
        let json = """
        {"resources":[{"id":"demo-link","type":"note","title":"GraphRecall docs (demo)","preview":"Sample documentation link for \(conceptName.replacingOccurrences(of: "\"", with: "")).","resource_type":"documentation","source_url":"https://github.com/usnaveen/GraphRecall"}]}
        """
        guard let data = json.data(using: .utf8),
              let decoded = try? JSONDecoder().decode(ConceptResourcesResponse.self, from: data)
        else { return [] }
        return decoded.resources
    }
}
