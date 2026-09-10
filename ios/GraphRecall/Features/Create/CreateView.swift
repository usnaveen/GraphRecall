import SwiftUI

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

    var isStub: Bool { self == .file }
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

    var parsedConcepts: [String] {
        conceptsText
            .split(whereSeparator: { $0 == "\n" || $0 == "," || $0 == ";" })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    var canSubmit: Bool {
        guard !isSubmitting, !mode.isStub else { return false }
        switch mode {
        case .concepts: return !parsedConcepts.isEmpty
        case .text, .chat: return !bodyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .url, .youtube:
            let raw = urlField.trimmingCharacters(in: .whitespacesAndNewlines)
            return URL(string: raw)?.scheme != nil && !raw.isEmpty
        case .file: return false
        }
    }

    var primaryButtonTitle: String {
        if isSubmitting {
            switch mode {
            case .concepts: return "Researching…"
            case .youtube: return "Saving…"
            default: return "Ingesting…"
            }
        }
        switch mode {
        case .concepts: return "Research & add to feed"
        case .text: return "Ingest text"
        case .url: return "Ingest URL"
        case .youtube: return "Save YouTube link"
        case .chat: return "Ingest transcript"
        case .file: return "Coming soon"
        }
    }

    func clearResults() {
        errorMessage = nil
        successMessage = nil
        lastDumpResponse = nil
        lastIngest = nil
        lastYouTube = nil
    }

    func selectMode(_ newMode: CreateIngestMode) {
        guard mode != newMode else { return }
        mode = newMode
        clearResults()
    }

    func submit() async {
        guard canSubmit else {
            if mode.isStub {
                errorMessage = nil
                successMessage = "File / ZIP ingest is coming soon."
            } else {
                errorMessage = "Fill in the required fields."
            }
            return
        }

        isSubmitting = true
        errorMessage = nil
        successMessage = nil
        lastDumpResponse = nil
        lastIngest = nil
        lastYouTube = nil
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
                successMessage = "File / ZIP ingest is coming soon."
            }
        } catch {
            errorMessage = APIError.userFacing(error, resource: "ingest")
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
                }
                .padding(.bottom, GRLayout.dockClearance)
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
        case .file: return "Upload files & processed ZIPs — coming soon"
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
            Text("PDF, markdown, and processed-book ZIP uploads will land here next. Use Text or URL for now.")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
            submitButton
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
}

#Preview { CreateView().preferredColorScheme(.dark) }
