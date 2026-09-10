import SwiftUI

/// Liquid Glass NotePanel — parity with web `NotePanel.tsx` (GET `/api/concepts/{id}/notes`).
struct GraphNotePanel: View {
    let conceptId: String
    let conceptName: String
    var isDemo: Bool = false
    var onClose: () -> Void

    @State private var notes: [ConceptNote] = []
    @State private var isLoading = true
    @State private var errorMessage: String?

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
        .task(id: conceptId) { await load() }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "book.fill")
                .foregroundStyle(GRColor.accent)
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 2) {
                Text("Notes: \(conceptName)")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                    .lineLimit(2)
                Text(subtitle)
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
            .accessibilityLabel("Close notes")
        }
        .padding(14)
    }

    private var subtitle: String {
        if isLoading { return "Loading…" }
        if isDemo { return "Demo · sample excerpts" }
        let n = notes.count
        return "\(n) source\(n == 1 ? "" : "s") found"
    }

    @ViewBuilder
    private var content: some View {
        if isLoading {
            HStack(spacing: 10) {
                ProgressView().tint(GRColor.accent)
                Text("Fetching linked notes…")
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textSecondary)
            }
            .frame(maxWidth: .infinity)
            .padding(28)
        } else if let errorMessage {
            VStack(spacing: 8) {
                Image(systemName: "exclamationmark.triangle")
                    .foregroundStyle(GRColor.warning)
                Text(errorMessage)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textSecondary)
                    .multilineTextAlignment(.center)
            }
            .padding(24)
            .frame(maxWidth: .infinity)
        } else if notes.isEmpty {
            VStack(spacing: 8) {
                Image(systemName: "doc.text")
                    .font(.system(size: 28))
                    .foregroundStyle(GRColor.textTertiary)
                Text("No notes linked to this concept")
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textSecondary)
                Text("Ingest content to see notes here")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
            }
            .padding(28)
            .frame(maxWidth: .infinity)
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    ForEach(notes) { note in
                        noteBlock(note)
                    }
                }
                .padding(14)
            }
            .frame(maxHeight: 360)
        }
    }

    private func noteBlock(_ note: ConceptNote) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text(note.title)
                    .font(GRType.caption.weight(.semibold))
                    .foregroundStyle(GRColor.accent)
                    .textCase(.uppercase)
                    .lineLimit(2)
                if let resourceType = note.resourceType, !resourceType.isEmpty {
                    Text(resourceType)
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 2)
                        .background(Capsule().fill(GRColor.fillSubtle))
                }
            }
            Divider().overlay(GRColor.stroke.opacity(0.6))

            let chunks = note.chunks.sorted { ($0.chunkIndex ?? 0) < ($1.chunkIndex ?? 0) }
            ForEach(chunks) { chunk in
                VStack(alignment: .leading, spacing: 4) {
                    if let page = chunk.pageStart {
                        let end = chunk.pageEnd
                        Text(end != nil && end != page ? "p. \(page)–\(end!)" : "p. \(page)")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                            .monospaced()
                    }
                    markdownBody(chunk.content)
                }
            }
        }
    }

    @ViewBuilder
    private func markdownBody(_ content: String) -> some View {
        if let attributed = try? AttributedString(
            markdown: content,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        ) {
            Text(attributed)
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
        } else {
            Text(content)
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
        }
    }

    private func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        if isDemo {
            notes = [
                ConceptNote(
                    id: "demo-note",
                    title: "Demo · GraphRecall Notes",
                    resourceType: "notes",
                    evidenceSpan: nil,
                    chunks: [
                        ConceptNoteChunk(
                            id: "c1",
                            content: "**\(conceptName)** appears in the demo graph. Connect the API to load real NoteSource → Concept excerpts.",
                            chunkIndex: 0
                        )
                    ]
                )
            ]
            return
        }

        do {
            let response = try await APIClient.shared.fetchConceptNotes(conceptId: conceptId)
            notes = response.notes
        } catch {
            errorMessage = APIError.userFacing(error, resource: "notes")
            notes = []
        }
    }
}
