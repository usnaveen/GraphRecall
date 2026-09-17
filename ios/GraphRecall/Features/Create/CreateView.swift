import SwiftUI
import UniformTypeIdentifiers
import PDFKit
import PhotosUI

enum CreateIngestMode: String, CaseIterable, Identifiable, Sendable {
    case concepts
    case text
    case url
    case youtube
    case chat
    case file
    case scan
    case voice

    var id: String { rawValue }

    var title: String {
        switch self {
        case .concepts: return "Concepts"
        case .text: return "Text"
        case .url: return "URL"
        case .youtube: return "YouTube"
        case .chat: return "Chat"
        case .file: return "File"
        case .scan: return "Scan"
        case .voice: return "Voice"
        }
    }

    var systemImage: String {
        switch self {
        case .concepts: return "lightbulb.fill"
        case .text: return "doc.text.fill"
        case .url: return "globe"
        case .youtube: return "play.rectangle.fill"
        case .chat: return "bubble.left.and.bubble.right.fill"
        case .file: return "square.and.arrow.up.fill"
        case .scan: return "doc.viewfinder"
        case .voice: return "mic.fill"
        }
    }

    var isNew: Bool { self == .scan || self == .voice }

    /// Modes whose text can go through human-in-the-loop concept review first.
    var supportsReview: Bool { self == .text || self == .scan || self == .voice || self == .file }
}

struct ReviewLaunch: Identifiable {
    let id: String
    let title: String
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
    var isRecognizing = false
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

    // Import review
    var reviewLaunch: ReviewLaunch?
    var pendingSessions: [PendingReviewSession] = []

    /// `resource_type` sent with direct (non-review) text and file ingests.
    var resourceType = "notes"
    static let resourceTypes: [(id: String, title: String, systemImage: String)] = [
        ("notes", "Notes", "note.text"),
        ("article", "Article", "newspaper"),
        ("lecture", "Lecture", "graduationcap"),
        ("paper", "Paper", "doc.richtext"),
        ("book", "Book", "book"),
    ]

    /// Links and text saved from the share sheet (App Group inbox).
    var sharedInbox: [GRSharedImport] = []

    func loadSharedInbox() {
        sharedInbox = GRShareInbox.load()
    }

    func useShared(_ item: GRSharedImport) {
        clearResults()
        switch item.kind {
        case .url:
            let lower = item.content.lowercased()
            mode = lower.contains("youtube.com") || lower.contains("youtu.be") ? .youtube : .url
            urlField = item.content
        case .text:
            mode = .text
            bodyText = item.content
        }
        titleField = item.title ?? ""
        GRShareInbox.remove(id: item.id)
        loadSharedInbox()
    }

    func dismissShared(_ item: GRSharedImport) {
        GRShareInbox.remove(id: item.id)
        loadSharedInbox()
    }

    var parsedConcepts: [String] {
        conceptsText
            .split(whereSeparator: { $0 == "\n" || $0 == "," || $0 == ";" })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    var canSubmit: Bool {
        guard !isSubmitting, !isRecognizing else { return false }
        switch mode {
        case .concepts: return !parsedConcepts.isEmpty
        case .text, .chat, .scan, .voice: return !bodyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .url, .youtube:
            let raw = urlField.trimmingCharacters(in: .whitespacesAndNewlines)
            return URL(string: raw)?.scheme != nil && !raw.isEmpty
        case .file: return selectedFileURL != nil
        }
    }

    func usesReview(_ enabled: Bool) -> Bool {
        enabled && mode.supportsReview && !(mode == .file && selectedFileIsZip)
    }

    func primaryButtonTitle(review: Bool) -> String {
        if isSubmitting {
            switch mode {
            case .concepts: return "Researching…"
            case .youtube: return "Saving…"
            case .file: return selectedFileIsZip ? "Uploading ZIP…" : "Ingesting file…"
            default: return review ? "Extracting concepts…" : "Ingesting…"
            }
        }
        if review { return "Extract & review concepts" }
        switch mode {
        case .concepts: return "Research & add to feed"
        case .text: return "Ingest text"
        case .url: return "Ingest URL"
        case .youtube: return "Save YouTube link"
        case .chat: return "Ingest transcript"
        case .file: return selectedFileIsZip ? "Upload processed ZIP" : "Ingest file"
        case .scan: return "Ingest scanned text"
        case .voice: return "Ingest voice note"
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

    func loadPendingSessions() async {
        pendingSessions = (try? await APIClient.shared.pendingReviewSessions()) ?? []
    }

    func recognize(images: [UIImage]) async {
        guard !images.isEmpty else { return }
        isRecognizing = true
        errorMessage = nil
        defer { isRecognizing = false }
        do {
            let text = try await TextRecognizer.recognizeText(in: images)
            if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                errorMessage = "No readable text found in those pages."
            } else {
                bodyText = bodyText.isEmpty ? text : bodyText + "\n\n" + text
                successMessage = "Read \(images.count) page\(images.count == 1 ? "" : "s") — edit if needed, then ingest."
            }
        } catch {
            errorMessage = "Couldn’t read text from the scan."
        }
    }

    func submit(review reviewEnabled: Bool) async {
        guard canSubmit else {
            errorMessage = "Fill in the required fields."
            return
        }
        let review = usesReview(reviewEnabled)

        isSubmitting = true
        clearResults()
        defer { isSubmitting = false }

        do {
            switch mode {
            case .concepts:
                let response = try await APIClient.shared.dumpConcepts(parsedConcepts)
                lastDumpResponse = response
                await OfflineReviewStore.shared.ingestDump(response)
                NotificationCenter.default.post(name: .grDumpCompleted, object: nil)
                successMessage = "Added \(response.succeeded)/\(response.processed) concepts — teach cards are in Today."
                RecentImportsStore.shared.add(RecentImport(
                    title: parsedConcepts.prefix(3).joined(separator: ", "),
                    kind: mode.title,
                    status: "added",
                    detail: "\(response.succeeded) concepts researched"
                ))

            case .text, .scan, .voice:
                let content = bodyText.trimmingCharacters(in: .whitespacesAndNewlines)
                let title = optionalTitle ?? defaultTitle
                if review {
                    try await submitForReview(content: content, title: title)
                } else {
                    let response = try await APIClient.shared.ingestText(content: content, title: title, resourceType: resourceType)
                    lastIngest = response
                    applyIngestSuccess(response, verb: mode.title, title: title)
                }

            case .url:
                let url = urlField.trimmingCharacters(in: .whitespacesAndNewlines)
                let response = try await APIClient.shared.ingestURL(url)
                lastIngest = response
                applyIngestSuccess(response, verb: "URL", title: URL(string: url)?.host() ?? url)

            case .youtube:
                let url = urlField.trimmingCharacters(in: .whitespacesAndNewlines)
                let response = try await APIClient.shared.ingestYouTube(url: url, title: optionalTitle)
                lastYouTube = response
                let note = response.noteId.map { " · note \($0.prefix(8))…" } ?? ""
                successMessage = "YouTube link \(response.status)\(note)"
                RecentImportsStore.shared.add(RecentImport(title: optionalTitle ?? url, kind: mode.title, status: response.status, detail: "Saved as a resource"))

            case .chat:
                let content = bodyText.trimmingCharacters(in: .whitespacesAndNewlines)
                let response = try await APIClient.shared.ingestChatTranscript(content: content, title: optionalTitle)
                lastIngest = response
                applyIngestSuccess(response, verb: "Chat transcript", title: optionalTitle ?? "Chat transcript")

            case .file:
                try await submitFile(review: review)
            }
        } catch {
            errorMessage = APIError.userFacing(error, resource: "ingest")
        }
    }

    private func submitForReview(content: String, title: String) async throws {
        let response = try await APIClient.shared.ingestWithReview(content: content)
        if let sessionId = response.sessionId {
            successMessage = "Found \(response.conceptsCount) concepts — approve them before they’re added."
            RecentImportsStore.shared.add(RecentImport(
                title: title,
                kind: mode.title,
                status: "review",
                detail: "\(response.conceptsCount) concepts waiting for approval",
                sessionId: sessionId
            ))
            reviewLaunch = ReviewLaunch(id: sessionId, title: title)
            await loadPendingSessions()
        } else {
            successMessage = response.message
            RecentImportsStore.shared.add(RecentImport(title: title, kind: mode.title, status: response.status, detail: response.message))
        }
    }

    private func submitFile(review: Bool) async throws {
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
            if !response.message.isEmpty {
                parts.append(response.message)
            }
            successMessage = parts.joined(separator: " · ")
            showLibraryLink = true
            RecentImportsStore.shared.add(RecentImport(title: title, kind: mode.title, status: response.status, detail: response.message))
        } else {
            let content = try CreateFileReader.extractText(from: fileURL)
            guard !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                errorMessage = "No extractable text in this file."
                return
            }
            if review {
                try await submitForReview(content: content, title: title)
                return
            }
            let response = try await APIClient.shared.ingestText(
                content: content,
                title: title,
                resourceType: resourceType
            )
            lastIngest = response
            applyIngestSuccess(response, verb: "File", title: title)
        }
    }

    private var optionalTitle: String? {
        let t = titleField.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }

    private var defaultTitle: String {
        switch mode {
        case .scan: return "Scanned pages"
        case .voice: return "Voice note"
        default: return "Text note"
        }
    }

    private func applyIngestSuccess(_ response: IngestResponse, verb: String, title: String) {
        if let err = response.error, response.status == "error" {
            errorMessage = err
            RecentImportsStore.shared.add(RecentImport(title: title, kind: mode.title, status: "error", detail: err))
            return
        }
        var parts: [String] = ["\(verb) \(response.status)"]
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
        RecentImportsStore.shared.add(RecentImport(
            title: title,
            kind: mode.title,
            status: response.status,
            detail: "\(response.conceptIds.count) concepts · \(response.flashcardIds.count) cards"
        ))
        if !response.flashcardIds.isEmpty {
            NotificationCenter.default.post(name: .grFeedShouldReload, object: nil)
        }
    }
}

struct CreateView: View {
    @State private var model = CreateViewModel()
    @State private var dictation = GRDictation()
    @State private var photoItems: [PhotosPickerItem] = []
    @State private var showScanner = false
    @AppStorage(GRSettingsKey.reviewImports) private var reviewImports = true
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        @Bindable var bindable = model

        ZStack {
            backgroundGlow
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    GRScreenHeader(title: "Create", subtitle: subtitleForMode)

                    if !model.sharedInbox.isEmpty {
                        sharedInboxSection
                            .padding(.horizontal, 20)
                    }

                    sourceGrid
                        .padding(.horizontal, 20)

                    GlassCard {
                        modeContent
                    }
                    .padding(.horizontal, 20)

                    feedback
                        .padding(.horizontal, 20)

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

                    if model.mode.supportsReview && !(model.mode == .file && model.selectedFileIsZip) {
                        optionsCard
                            .padding(.horizontal, 20)
                    }

                    pendingSection
                        .padding(.horizontal, 20)

                    recentSection
                        .padding(.horizontal, 20)
                }
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .fileImporter(
            isPresented: $bindable.showFileImporter,
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
        .onChange(of: photoItems) { _, items in
            Task { await loadPhotos(items) }
        }
        .fullScreenCover(isPresented: $showScanner) {
            DocumentScannerView(
                onFinish: { images in
                    showScanner = false
                    Task { await model.recognize(images: images) }
                },
                onCancel: { showScanner = false }
            )
            .ignoresSafeArea()
        }
        .sheet(item: $bindable.reviewLaunch) { launch in
            ImportReviewView(sessionId: launch.id, sourceTitle: launch.title) { message in
                model.successMessage = message
                Task { await model.loadPendingSessions() }
            }
        }
        .task {
            model.loadSharedInbox()
            await model.loadPendingSessions()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { model.loadSharedInbox() }
        }
        .onDisappear { dictation.stop() }
    }

    private var subtitleForMode: String {
        switch model.mode {
        case .concepts: return "Dump concepts to research — teach cards land in Today"
        case .text: return "Paste notes or markdown — extracted into your graph"
        case .url: return "Ingest an article from a URL (Substack, Medium, blogs)"
        case .youtube: return "Save a YouTube link as a resource"
        case .chat: return "Paste an LLM chat transcript (Human: / AI:)"
        case .file: return "PDF, markdown, text, or processed-book ZIP"
        case .scan: return "Scan pages or pick photos — text is read on-device"
        case .voice: return "Talk through what you learned"
        }
    }

    // MARK: - Source grid

    private var sourceGrid: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: 4), spacing: 10) {
            ForEach(CreateIngestMode.allCases) { mode in
                let selected = model.mode == mode
                Button {
                    dictation.stop()
                    withAnimation(.easeOut(duration: 0.18)) { model.selectMode(mode) }
                    GRHaptics.tap()
                } label: {
                    VStack(spacing: 6) {
                        Image(systemName: mode.systemImage)
                            .font(.system(size: 19, weight: .semibold))
                        Text(mode.title)
                            .font(GRType.caption.weight(.bold))
                            .lineLimit(1)
                            .minimumScaleFactor(0.8)
                    }
                    .foregroundStyle(selected ? GRColor.accent : GRColor.textPrimary)
                    .frame(maxWidth: .infinity)
                    .frame(height: 74)
                    .background {
                        if selected {
                            RoundedRectangle(cornerRadius: 16, style: .continuous).fill(GRColor.accentSoft)
                        } else {
                            Color.clear.grGlassEffect(.interactive, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                        }
                    }
                    .overlay(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .stroke(selected ? GRColor.accentLine : GRColor.stroke, lineWidth: 1)
                    )
                    .overlay(alignment: .topTrailing) {
                        if mode.isNew {
                            Text("NEW")
                                .font(GRType.micro.weight(.heavy))
                                .foregroundStyle(GRColor.canvas)
                                .padding(.horizontal, 5)
                                .padding(.vertical, 2)
                                .background(GRColor.accent, in: Capsule())
                                .padding(5)
                        }
                    }
                }
                .buttonStyle(.plain)
                .accessibilityLabel(mode.title)
                .accessibilityAddTraits(selected ? .isSelected : [])
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
            fileForm
        case .scan:
            scanForm
        case .voice:
            voiceForm
        }
    }

    // MARK: - Forms

    private var conceptsForm: some View {
        @Bindable var bindable = model
        return VStack(alignment: .leading, spacing: 12) {
            Text("Concept dump")
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
            Text("One per line (or commas). We research each concept, link it into your graph and build cards.")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)

            editor(text: $bindable.conceptsText, minHeight: 130)

            HStack {
                dictateButton {
                    Task { await toggleDictation(into: \.conceptsText, separator: "\n") }
                }
                Spacer()
                if !model.parsedConcepts.isEmpty {
                    Text("\(model.parsedConcepts.count) ready")
                        .font(GRType.caption.weight(.bold))
                        .foregroundStyle(GRColor.accent)
                }
            }

            if !model.parsedConcepts.isEmpty {
                GRFlowLayout(spacing: 6, lineSpacing: 6) {
                    ForEach(Array(model.parsedConcepts.prefix(24).enumerated()), id: \.offset) { _, concept in
                        GRChip(title: concept, systemImage: "checkmark", style: .tinted(.accent), compact: true)
                    }
                }
            }

            submitButton
        }
    }

    private enum TextFormKind { case text, chat }

    private func textForm(kind: TextFormKind) -> some View {
        @Bindable var bindable = model
        return VStack(alignment: .leading, spacing: 12) {
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
            editor(text: $bindable.bodyText, minHeight: kind == .chat ? 180 : 160)
            submitButton
        }
    }

    private func urlForm(youtube: Bool) -> some View {
        @Bindable var bindable = model
        return VStack(alignment: .leading, spacing: 12) {
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

            HStack(spacing: 8) {
                TextField(youtube ? "https://youtube.com/watch?v=…" : "https://…", text: $bindable.urlField)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
                    .foregroundStyle(GRColor.textPrimary)
                    .font(GRType.body)
                if let pasted = UIPasteboard.general.hasURLs ? "Paste" : nil {
                    Button(pasted) {
                        if let url = UIPasteboard.general.url {
                            model.urlField = url.absoluteString
                        } else if let string = UIPasteboard.general.string {
                            model.urlField = string
                        }
                    }
                    .font(GRType.caption.weight(.bold))
                    .foregroundStyle(GRColor.accent)
                }
            }
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(GRColor.fillSubtle)
            )

            submitButton
        }
    }

    private var fileForm: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("File / ZIP")
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
            Text("PDF, Markdown and text files are read on-device and ingested. Processed-book ZIPs upload to your Library.")
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
                        GRChip(title: "ZIP", style: .tinted(.cyan), compact: true)
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
                    Label("Open Library", systemImage: "books.vertical.fill")
                }
                .buttonStyle(.grGhost)
            }
        }
    }

    private var scanForm: some View {
        @Bindable var bindable = model
        return VStack(alignment: .leading, spacing: 12) {
            Text("Scan pages")
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
            Text("Photograph book pages, slides or whiteboards. Text is recognised on-device, then turned into concepts and cards.")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)

            HStack(spacing: 10) {
                Button {
                    showScanner = true
                } label: {
                    Label(DocumentScannerView.isSupported ? "Scan" : "No camera", systemImage: "camera.fill")
                }
                .buttonStyle(GRButtonStyle(kind: .secondary, compact: true))
                .disabled(!DocumentScannerView.isSupported)

                PhotosPicker(selection: $photoItems, maxSelectionCount: 6, matching: .images) {
                    Label("From Photos", systemImage: "photo.on.rectangle")
                }
                .buttonStyle(GRButtonStyle(kind: .secondary, compact: true))
            }

            if model.isRecognizing {
                HStack(spacing: 8) {
                    ProgressView().tint(GRColor.accent)
                    Text("Reading text…")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
            }

            if !model.bodyText.isEmpty {
                titleField
                editor(text: $bindable.bodyText, minHeight: 160)
                submitButton
            }
        }
    }

    private var voiceForm: some View {
        @Bindable var bindable = model
        return VStack(alignment: .leading, spacing: 14) {
            Text("Voice note")
                .font(GRType.headline)
                .foregroundStyle(GRColor.textPrimary)
            Text("Explain what you learned out loud. We transcribe on-device, extract concepts and build cards.")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)

            HStack {
                Spacer()
                Button {
                    Task { await toggleDictation(into: \.bodyText, separator: " ") }
                } label: {
                    ZStack {
                        Circle()
                            .fill(dictation.isRecording ? GRColor.danger.opacity(0.18) : GRColor.accentSoft)
                        Circle()
                            .stroke(dictation.isRecording ? GRColor.danger : GRColor.accentLine, lineWidth: 2)
                        Image(systemName: dictation.isRecording ? "stop.fill" : "mic.fill")
                            .font(.system(size: 32, weight: .bold))
                            .foregroundStyle(dictation.isRecording ? GRColor.danger : GRColor.accent)
                            .symbolEffect(.pulse, isActive: dictation.isRecording)
                    }
                    .frame(width: 96, height: 96)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(dictation.isRecording ? "Stop dictation" : "Start dictation")
                Spacer()
            }

            Text(dictation.isRecording ? "Listening… tap to stop" : (model.bodyText.isEmpty ? "Tap to start dictating" : "Tap to add more"))
                .font(GRType.caption)
                .foregroundStyle(GRColor.textTertiary)
                .frame(maxWidth: .infinity)

            if !model.bodyText.isEmpty {
                titleField
                editor(text: $bindable.bodyText, minHeight: 130)
                submitButton
            }
        }
    }

    // MARK: - Shared form pieces

    private var titleField: some View {
        @Bindable var bindable = model
        return TextField("Title (optional)", text: $bindable.titleField)
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

    private func dictateButton(action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(dictation.isRecording ? "Stop" : "Dictate", systemImage: dictation.isRecording ? "stop.circle.fill" : "mic.fill")
                .font(GRType.caption.weight(.bold))
                .foregroundStyle(dictation.isRecording ? GRColor.danger : GRColor.accent)
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .background(dictation.isRecording ? GRColor.danger.opacity(0.15) : GRColor.accentSoft, in: Capsule())
        }
        .buttonStyle(.plain)
    }

    private var submitButton: some View {
        let review = model.usesReview(reviewImports)
        return Button {
            dictation.stop()
            Task { await model.submit(review: reviewImports) }
        } label: {
            HStack(spacing: 8) {
                if model.isSubmitting { ProgressView().tint(GRColor.canvas) }
                Text(model.primaryButtonTitle(review: review))
            }
        }
        .buttonStyle(.grPrimary)
        .disabled(!model.canSubmit)
    }

    @ViewBuilder
    private var feedback: some View {
        if let err = model.errorMessage {
            GRBanner(systemImage: "exclamationmark.triangle.fill", title: "Something went wrong", subtitle: err, tone: .warning)
        }
        if let ok = model.successMessage {
            GRBanner(systemImage: "checkmark.circle.fill", title: "Done", subtitle: ok, tone: .accent)
        }
    }

    private var optionsCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 14) {
                Toggle(isOn: $reviewImports) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Review before adding")
                            .font(GRType.headline)
                            .foregroundStyle(GRColor.textPrimary)
                        Text("Approve extracted concepts and skip duplicates first")
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textSecondary)
                    }
                }
                .tint(GRColor.accent)

                if !model.usesReview(reviewImports) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Save as")
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textTertiary)
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 8) {
                                ForEach(CreateViewModel.resourceTypes, id: \.id) { type in
                                    GRChip(
                                        title: type.title,
                                        systemImage: type.systemImage,
                                        style: model.resourceType == type.id ? .selected : .plain,
                                        compact: true
                                    ) {
                                        model.resourceType = type.id
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private var sharedInboxSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "Shared to GraphRecall")
            ForEach(model.sharedInbox) { item in
                GlassCard(cornerRadius: 18) {
                    HStack(spacing: 12) {
                        GRIconTile(
                            systemImage: item.kind == .url ? "globe" : "doc.text.fill",
                            tone: item.kind == .url ? .cyan : .accent,
                            size: 36
                        )
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.displayTitle)
                                .font(GRType.headline)
                                .foregroundStyle(GRColor.textPrimary)
                                .lineLimit(1)
                            Text(item.content)
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textSecondary)
                                .lineLimit(1)
                        }
                        Spacer(minLength: 8)
                        GRChip(title: "Use", systemImage: "arrow.down.to.line", style: .selected, compact: true) {
                            model.useShared(item)
                            GRHaptics.tap()
                        }
                        GRIconButton(systemImage: "xmark", style: .plain, tint: GRColor.textTertiary, size: 30, accessibilityLabel: "Dismiss shared item") {
                            model.dismissShared(item)
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var pendingSection: some View {
        if !model.pendingSessions.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                GRSectionHeader(title: "Needs your review")
                ForEach(model.pendingSessions) { session in
                    Button {
                        model.reviewLaunch = ReviewLaunch(id: session.sessionId, title: "Review import")
                    } label: {
                        GRListRow(
                            title: "\(session.conceptsCount) concepts waiting",
                            subtitle: "Extracted \(ProfileDateFormat.short(session.createdAt))",
                            meta: "Review",
                            metaColor: GRColor.amber,
                            systemImage: "sparkles",
                            tone: .amber
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    @ViewBuilder
    private var recentSection: some View {
        let recents = RecentImportsStore.shared.items
        if !recents.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                GRSectionHeader(title: "Recent imports", actionTitle: "Clear") {
                    RecentImportsStore.shared.clear()
                }
                ForEach(recents.prefix(5)) { item in
                    let style = recentStyle(item)
                    Button {
                        if item.status == "review", let sessionId = item.sessionId {
                            model.reviewLaunch = ReviewLaunch(id: sessionId, title: item.title)
                        }
                    } label: {
                        GRListRow(
                            title: item.title,
                            subtitle: "\(item.kind) · \(item.detail)",
                            meta: style.meta,
                            metaColor: style.tone.color,
                            systemImage: style.icon,
                            tone: style.tone,
                            showsChevron: item.status == "review"
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func recentStyle(_ item: RecentImport) -> (meta: String, tone: GRTone, icon: String) {
        let kindIcon = CreateIngestMode.allCases.first { $0.title == item.kind }?.systemImage ?? "tray.full.fill"
        switch item.status {
        case "review": return ("Review", .amber, "sparkles")
        case "error": return ("Failed", .danger, "exclamationmark.triangle.fill")
        case "discarded": return ("Discarded", .neutral, kindIcon)
        default: return ("Done", .accent, kindIcon)
        }
    }

    private func toggleDictation(into keyPath: ReferenceWritableKeyPath<CreateViewModel, String>, separator: String) async {
        if dictation.isRecording {
            dictation.stop()
            return
        }
        let current = model[keyPath: keyPath]
        let base = current.isEmpty ? "" : current + separator
        let target = model
        await dictation.start { text in
            target[keyPath: keyPath] = base + text
        }
        if let err = dictation.errorMessage {
            model.errorMessage = err
        }
    }

    private func loadPhotos(_ items: [PhotosPickerItem]) async {
        guard !items.isEmpty else { return }
        var images: [UIImage] = []
        for item in items {
            if let data = try? await item.loadTransferable(type: Data.self), let image = UIImage(data: data) {
                images.append(image)
            }
        }
        photoItems = []
        await model.recognize(images: images)
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

    // MARK: - Results

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
                        .foregroundStyle(response.status == "error" ? GRColor.warning : GRColor.accent)
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
                        .foregroundStyle(response.status == "error" ? GRColor.warning : GRColor.accent)
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
                userInfo: [NSLocalizedDescriptionKey: "PDF has no extractable text (scanned image?) — try Scan instead."]
            )
        }
        let name = url.deletingPathExtension().lastPathComponent
        return "Draft Note: \(name)\n\n\(text)"
    }
}

#Preview { CreateView().preferredColorScheme(.dark) }
