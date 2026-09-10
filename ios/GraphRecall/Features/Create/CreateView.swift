import SwiftUI
import UniformTypeIdentifiers
import PDFKit

enum CreateIngestMode: String, CaseIterable, Identifiable, Sendable {
    case concepts
    case text
    case url
    case youtube
    case chat
    case file

    var id: String { rawValue }

    var title: String {
        switch self {
        case .concepts: return "Concepts"
        case .text: return "Text"
        case .url: return "URL"
        case .youtube: return "YouTube"
        case .chat: return "Chat"
        case .file: return "File"
        }
    }

    var isStub: Bool { false }
}

@MainActor
@Observable
final class CreateViewModel {
    var mode: CreateIngestMode = .concepts

    var conceptsText: String = ""
    var lastDumpResponse: ConceptDumpResponse?

    var titleField: String = ""
    var bodyText: String = ""
    var urlField: String = ""

    var isSubmitting = false
    var errorMessage: String?
    var successMessage: String?
    var lastIngest: IngestResponse?
    var lastYouTube: IngestYouTubeResponse?
    var lastZip: ProcessedZipIngestResponse?

    // File / ZIP picker
    var showFileImporter = false
    var selectedFileName: String?
    var selectedFileURL: URL?
    var selectedFileIsZip = false
    var showLibraryLink = false

    var parsedConcepts: [String] {
        conceptsText
            .split(whereSeparator: { $0 == "\n" || $0 == "," || $0 == ";" })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    var canSubmit: Bool {
        guard !isSubmitting else { return false }
        switch mode {
        case .concepts: return !parsedConcepts.isEmpty
        case .text, .chat: return !bodyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .url, .youtube:
            let raw = urlField.trimmingCharacters(in: .whitespacesAndNewlines)
            return URL(string: raw)?.scheme != nil && !raw.isEmpty
        case .file: return selectedFileURL != nil
        }
    }

    var primaryButtonTitle: String {
        if isSubmitting {
            switch mode {
            case .concepts: return "Researching…"
            case .youtube: return "Saving…"
            case .file: return selectedFileIsZip ? "Uploading ZIP…" : "Ingesting file…"
            default: return "Ingesting…"
            }
        }
        switch mode {
        case .concepts: return "Research & add to feed"
        case .text: return "Ingest text"
        case .url: return "Ingest URL"
        case .youtube: return "Save YouTube link"
        case .chat: return "Ingest transcript"
        case .file: return selectedFileIsZip ? "Upload processed ZIP" : "Ingest file"
        }
    }

    func clearResults() {
        errorMessage = nil
        successMessage = nil
        lastDumpResponse = nil
        lastIngest = nil
        lastYouTube = nil
        lastZip = nil
        showLibraryLink = false
    }

    func clearSelectedFile() {
        selectedFileName = nil
        selectedFileURL = nil
        selectedFileIsZip = false
    }

    func applyPickedFile(url: URL) {
        let accessed = url.startAccessingSecurityScopedResource()
        defer { if accessed { url.stopAccessingSecurityScopedResource() } }

        // Copy into temp so the security-scoped bookmark isn't required later.
        let ext = url.pathExtension.lowercased()
        let name = url.lastPathComponent
        let dest = FileManager.default.temporaryDirectory
            .appendingPathComponent("gr-ingest-\(UUID().uuidString)-\(name)")
        try? FileManager.default.removeItem(at: dest)
        do {
            try FileManager.default.copyItem(at: url, to: dest)
            selectedFileURL = dest
            selectedFileName = name
            selectedFileIsZip = (ext == "zip")
            clearResults()
        } catch {
            errorMessage = "Couldn’t read file: \(error.localizedDescription)"
            clearSelectedFile()
        }
    }

    func selectMode(_ newMode: CreateIngestMode) {
        guard mode != newMode else { return }
        mode = newMode
        clearResults()
    }

    func submit() async {
        guard canSubmit else {
            errorMessage = "Fill in the required fields."
            return
        }

        isSubmitting = true
        errorMessage = nil
        successMessage = nil
        lastDumpResponse = nil
        lastIngest = nil
        lastYouTube = nil
        lastZip = nil
        showLibraryLink = false
        defer { isSubmitting = false }

        do {
            switch mode {
            case .concepts:
                let response = try await APIClient.shared.dumpConcepts(parsedConcepts)
                lastDumpResponse = response
                await OfflineReviewStore.shared.ingestDump(response)
                NotificationCenter.default.post(name: .grDumpCompleted, object: nil)
                successMessage = "Added \(response.succeeded)/\(response.processed) concepts."

            case .text:
                let content = bodyText.trimmingCharacters(in: .whitespacesAndNewlines)
                let response = try await APIClient.shared.ingestText(content: content, title: optionalTitle)
                lastIngest = response
                applyIngestSuccess(response, verb: "Text")

            case .url:
                let url = urlField.trimmingCharacters(in: .whitespacesAndNewlines)
                let response = try await APIClient.shared.ingestURL(url)
                lastIngest = response
                applyIngestSuccess(response, verb: "URL")

            case .youtube:
                let url = urlField.trimmingCharacters(in: .whitespacesAndNewlines)
                let response = try await APIClient.shared.ingestYouTube(url: url, title: optionalTitle)
                lastYouTube = response
                let note = response.noteId.map { " · note \($0.prefix(8))…" } ?? ""
                successMessage = "YouTube link \(response.status)\(note)"

            case .chat:
                let content = bodyText.trimmingCharacters(in: .whitespacesAndNewlines)
                let response = try await APIClient.shared.ingestChatTranscript(
                    content: content,
                    title: optionalTitle
                )
                lastIngest = response
                applyIngestSuccess(response, verb: "Chat transcript")

            case .file:
                try await submitFile()
            }
        } catch {
            errorMessage = APIError.userFacing(error, resource: "ingest")
        }
    }


    private func submitFile() async throws {
        guard let fileURL = selectedFileURL else {
            errorMessage = "Pick a file first."
            return
        }
        let name = selectedFileName ?? fileURL.lastPathComponent
        let title = optionalTitle ?? name.replacingOccurrences(
            of: #"\.\w+$"#,
            with: "",
            options: .regularExpression
        )

        if selectedFileIsZip {
            let response = try await APIClient.shared.ingestProcessedZip(
                fileURL: fileURL,
                title: title,
                resourceType: "book",
                skipReview: true
            )
            lastZip = response
            if let err = response.error, response.status == "error" {
                errorMessage = err
                return
            }
            var parts: [String] = ["ZIP \(response.status)"]
            if !response.threadId.isEmpty {
                parts.append("thread \(shortId(response.threadId))")
            }
            if !response.message.isEmpty {
                parts.append(response.message)
            }
            successMessage = parts.joined(separator: " · ")
            showLibraryLink = true
        } else {
            let content = try CreateFileReader.extractText(from: fileURL)
            guard !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                errorMessage = "No extractable text in this file."
                return
            }
            let response = try await APIClient.shared.ingestText(
                content: content,
                title: title,
                resourceType: "notes"
            )
            lastIngest = response
            applyIngestSuccess(response, verb: "File")
        }
    }

    private var optionalTitle: String? {
        let t = titleField.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }

    private func applyIngestSuccess(_ response: IngestResponse, verb: String) {
        if let err = response.error, response.status == "error" {
            errorMessage = err
            return
        }
        var parts: [String] = ["\(verb) \(response.status)"]
        if !response.threadId.isEmpty, response.threadId != "duplicate_skipped" {
            parts.append("thread \(shortId(response.threadId))")
        }
        if let noteId = response.noteId, !noteId.isEmpty {
            parts.append("note \(shortId(noteId))")
        }
        if !response.conceptIds.isEmpty {
            parts.append("\(response.conceptIds.count) concepts")
        }
        if !response.flashcardIds.isEmpty {
            parts.append("\(response.flashcardIds.count) cards")
        }
        if let err = response.error, !err.isEmpty, response.statusReason.contains("duplicate") {
            parts.append(err)
        }
        successMessage = parts.joined(separator: " · ")
    }

    private func shortId(_ id: String) -> String {
        guard id.count > 10 else { return id }
        return String(id.prefix(8)) + "…"
    }
}

struct CreateView: View {
    @State private var model = CreateViewModel()

    var body: some View {
        ZStack {
            backgroundGlow
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    GRScreenHeader(
                        title: "Create",
                        subtitle: subtitleForMode
                    )

                    modePicker
                        .padding(.horizontal, 20)

                    GlassCard {
                        modeContent
                    }
                    .padding(.horizontal, 20)

                    if let err = model.errorMessage {
                        Text(err)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.warning)
                            .padding(.horizontal, 20)
                    }

                    if let ok = model.successMessage {
                        Text(ok)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.accent)
                            .padding(.horizontal, 20)
                    }

                    if let response = model.lastDumpResponse {
                        dumpResultsSection(response)
                            .padding(.horizontal, 20)
                    }

                    if let ingest = model.lastIngest {
                        ingestSummaryCard(ingest)
                            .padding(.horizontal, 20)
                    }

                    if let zip = model.lastZip {
                        zipSummaryCard(zip)
                            .padding(.horizontal, 20)
                    }
                }
                .padding(.bottom, GRLayout.dockClearance)
            }
        }
        .fileImporter(
            isPresented: $model.showFileImporter,
            allowedContentTypes: CreateFileReader.allowedTypes,
            allowsMultipleSelection: false
        ) { result in
            switch result {
            case .success(let urls):
                if let url = urls.first {
                    model.applyPickedFile(url: url)
                }
            case .failure(let error):
                model.errorMessage = APIError.userFacing(error, resource: "file picker")
            }
        }
    }

    private var subtitleForMode: String {
        switch model.mode {
        case .concepts: return "Dump concepts to research — teach cards land in your feed"
        case .text: return "Paste notes or markdown — extracted into your graph"
        case .url: return "Ingest an article from a URL (Substack, Medium, blogs)"
        case .youtube: return "Save a YouTube link as a resource (no transcript processing)"
        case .chat: return "Paste an LLM chat transcript (Human: / AI:)"
        case .file: return "PDF, markdown, text, or processed-book ZIP → your graph / library"
        }
    }

    private var modePicker: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(CreateIngestMode.allCases) { mode in
                    Button {
                        model.selectMode(mode)
                    } label: {
                        HStack(spacing: 4) {
                            Text(mode.title)
                                .font(GRType.caption)
                            if mode.isStub {
                                Text("Soon")
                                    .font(GRType.micro)
                                    .opacity(0.7)
                            }
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .foregroundStyle(model.mode == mode ? GRColor.canvas : GRColor.textSecondary)
                        .background {
                            Capsule(style: .continuous)
                                .fill(model.mode == mode ? GRColor.accent : GRColor.fillSubtle)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    @ViewBuilder
    private var modeContent: some View {
        switch model.mode {
        case .concepts:
            conceptsForm
        case .text:
            textForm(kind: .text)
        case .url:
            urlForm(youtube: false)
        case .youtube:
            urlForm(youtube: true)
        case .chat:
            textForm(kind: .chat)
        case .file:
            fileStub
        }
    }

    private var conceptsForm: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Concept dump")
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
            Text("One per line (or commas). We'll pull Wikipedia/articles and build cards.")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)

            editor(text: $model.conceptsText, minHeight: 140)

            if !model.parsedConcepts.isEmpty {
                Text("\(model.parsedConcepts.count) concepts ready")
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.accent)
            }

            submitButton
        }
    }

    private enum TextFormKind { case text, chat }

    private func textForm(kind: TextFormKind) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(kind == .text ? "Text / notes" : "Chat transcript")
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
            Text(
                kind == .text
                    ? "Paste markdown or plain text. Concepts and cards are generated automatically."
                    : "Paste a Human:/AI: transcript. We'll consolidate and ingest it."
            )
            .font(GRType.caption)
            .foregroundStyle(GRColor.textSecondary)

            titleField
            editor(text: $model.bodyText, minHeight: kind == .chat ? 180 : 160)
            submitButton
        }
    }

    private func urlForm(youtube: Bool) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(youtube ? "YouTube link" : "Article URL")
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
            Text(
                youtube
                    ? "Stored as a resource and linked — no transcript processing yet."
                    : "Fetches the page, extracts content, and adds it to your graph."
            )
            .font(GRType.caption)
            .foregroundStyle(GRColor.textSecondary)

            if youtube { titleField }

            TextField(youtube ? "https://youtube.com/watch?v=…" : "https://…", text: $model.urlField)
                .textInputAutocapitalization(.never)
                .keyboardType(.URL)
                .autocorrectionDisabled()
                .padding(12)
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(GRColor.fillSubtle)
                )
                .foregroundStyle(GRColor.textPrimary)
                .font(GRType.body)

            submitButton
        }
    }

    private var fileStub: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("File / ZIP")
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
            Text("Documents (PDF, .md, .txt) extract text and POST /api/v2/ingest. Processed ZIPs upload multipart to /api/v2/ingest/processed-zip.")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)

            titleField

            Button {
                model.showFileImporter = true
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "doc.badge.plus")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(GRColor.accent)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(model.selectedFileName == nil ? "Choose file" : "Change file")
                            .font(GRType.headline)
                            .foregroundStyle(GRColor.textPrimary)
                        Text(model.selectedFileName ?? "PDF · Markdown · Text · ZIP")
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textSecondary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                    if model.selectedFileIsZip {
                        Text("ZIP")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.accentCyan)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(Capsule().fill(GRColor.accentCyan.opacity(0.15)))
                    }
                }
                .padding(12)
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(GRColor.fillSubtle)
                )
            }
            .buttonStyle(.plain)

            if model.selectedFileURL != nil {
                Button("Clear selection") {
                    model.clearSelectedFile()
                    model.clearResults()
                }
                .font(GRType.caption)
                .foregroundStyle(GRColor.textTertiary)
            }

            submitButton

            if model.showLibraryLink {
                Button {
                    NotificationCenter.default.post(name: .grNavigateLibrary, object: nil)
                } label: {
                    HStack {
                        Image(systemName: "books.vertical.fill")
                        Text("Open Library")
                            .font(GRType.headline)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .foregroundStyle(GRColor.accent)
                    .background(
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .stroke(GRColor.accent.opacity(0.4), lineWidth: 1)
                    )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var titleField: some View {
        TextField("Title (optional)", text: $model.titleField)
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(GRColor.fillSubtle)
            )
            .foregroundStyle(GRColor.textPrimary)
            .font(GRType.body)
    }

    private func editor(text: Binding<String>, minHeight: CGFloat) -> some View {
        TextEditor(text: text)
            .frame(minHeight: minHeight)
            .scrollContentBackground(.hidden)
            .padding(10)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(GRColor.fillSubtle)
            )
            .foregroundStyle(GRColor.textPrimary)
            .font(GRType.body)
    }

    private var submitButton: some View {
        Button {
            Task { await model.submit() }
        } label: {
            HStack {
                if model.isSubmitting { ProgressView().tint(.black) }
                Text(model.primaryButtonTitle)
                    .font(GRType.headline)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .foregroundStyle(model.canSubmit ? GRColor.canvas : GRColor.textTertiary)
            .background {
                Group {
                    if model.canSubmit {
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .fill(
                                LinearGradient(
                                    colors: [GRColor.accent, GRColor.accentCyan],
                                    startPoint: .leading,
                                    endPoint: .trailing
                                )
                            )
                    } else {
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .fill(GRColor.fillSubtle)
                    }
                }
            }
        }
        .disabled(!model.canSubmit)
    }

    private var backgroundGlow: some View {
        ZStack {
            Circle()
                .fill(GRColor.accent.opacity(0.12))
                .frame(width: 280, height: 280)
                .blur(radius: 60)
                .offset(x: 120, y: -180)
            Circle()
                .fill(GRColor.accentCyan.opacity(0.10))
                .frame(width: 260, height: 260)
                .blur(radius: 50)
                .offset(x: -140, y: 220)
        }
        .allowsHitTesting(false)
    }

    @ViewBuilder
    private func dumpResultsSection(_ response: ConceptDumpResponse) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Added \(response.succeeded)/\(response.processed)")
                .font(GRType.title)
                .foregroundStyle(GRColor.textPrimary)

            ForEach(response.results) { item in
                GlassCard(cornerRadius: 16) {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text(item.concept)
                                .font(GRType.headline)
                                .foregroundStyle(GRColor.textPrimary)
                            Spacer()
                            Text(item.status == "ok" ? "Ready" : "Failed")
                                .font(GRType.caption)
                                .foregroundStyle(item.status == "ok" ? GRColor.accent : GRColor.warning)
                        }
                        if !item.sources.isEmpty {
                            Text("Sources")
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textSecondary)
                            ForEach(item.sources.prefix(3)) { src in
                                if let url = URL(string: src.url), !src.url.isEmpty {
                                    Link(src.title.isEmpty ? src.url : src.title, destination: url)
                                        .font(GRType.caption)
                                        .foregroundStyle(GRColor.accentCyan)
                                } else {
                                    Text(src.title)
                                        .font(GRType.caption)
                                        .foregroundStyle(GRColor.textSecondary)
                                }
                            }
                        }
                        if !item.cards.isEmpty {
                            Text("\(item.cards.count) teach cards queued")
                                .font(GRType.micro)
                                .foregroundStyle(GRColor.textTertiary)
                        }
                    }
                }
            }
        }
    }

    private func ingestSummaryCard(_ response: IngestResponse) -> some View {
        GlassCard(cornerRadius: 16) {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Ingest result")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Spacer()
                    Text(response.status)
                        .font(GRType.caption)
                        .foregroundStyle(
                            response.status == "error" ? GRColor.warning : GRColor.accent
                        )
                }
                if !response.threadId.isEmpty {
                    Text("thread_id: \(response.threadId)")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                        .textSelection(.enabled)
                }
                if let noteId = response.noteId {
                    Text("note_id: \(noteId)")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                        .textSelection(.enabled)
                }
                if !response.conceptIds.isEmpty || !response.flashcardIds.isEmpty {
                    Text("\(response.conceptIds.count) concepts · \(response.flashcardIds.count) flashcards")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
                if let err = response.error, !err.isEmpty {
                    Text(err)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.warning)
                }
            }
        }
    }

    private func zipSummaryCard(_ response: ProcessedZipIngestResponse) -> some View {
        GlassCard(cornerRadius: 16) {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("ZIP queued")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Spacer()
                    Text(response.status)
                        .font(GRType.caption)
                        .foregroundStyle(
                            response.status == "error" ? GRColor.warning : GRColor.accent
                        )
                }
                if !response.threadId.isEmpty {
                    Text("thread_id: \(response.threadId)")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                        .textSelection(.enabled)
                }
                if !response.message.isEmpty {
                    Text(response.message)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
                if let err = response.error, !err.isEmpty {
                    Text(err)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.warning)
                }
            }
        }
    }
}

enum CreateFileReader {
    static var allowedTypes: [UTType] {
        var types: [UTType] = [.pdf, .plainText, .utf8PlainText, .zip]
        if let md = UTType(filenameExtension: "md") { types.append(md) }
        if let markdown = UTType(filenameExtension: "markdown") { types.append(markdown) }
        return types
    }

    static func extractText(from url: URL) throws -> String {
        let ext = url.pathExtension.lowercased()
        switch ext {
        case "pdf":
            return try extractPDF(url)
        case "md", "markdown", "txt", "text", "":
            return try String(contentsOf: url, encoding: .utf8)
        default:
            // Best-effort UTF-8 for unknown text-like types
            if let s = try? String(contentsOf: url, encoding: .utf8), !s.isEmpty {
                return s
            }
            throw NSError(
                domain: "CreateFileReader",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Unsupported file type .\(ext). Use PDF, Markdown, TXT, or ZIP."]
            )
        }
    }

    private static func extractPDF(_ url: URL) throws -> String {
        guard let doc = PDFDocument(url: url) else {
            throw NSError(
                domain: "CreateFileReader",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "Couldn’t open PDF."]
            )
        }
        var parts: [String] = []
        for i in 0..<doc.pageCount {
            if let page = doc.page(at: i), let s = page.string {
                parts.append(s)
            }
        }
        let text = parts.joined(separator: "\n\n")
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            throw NSError(
                domain: "CreateFileReader",
                code: 3,
                userInfo: [NSLocalizedDescriptionKey: "PDF has no extractable text (scanned image?)."]
            )
        }
        let name = url.deletingPathExtension().lastPathComponent
        return "Draft Note: \(name)\n\n\(text)"
    }
}

#Preview { CreateView().preferredColorScheme(.dark) }
