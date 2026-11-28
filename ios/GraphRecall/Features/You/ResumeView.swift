import SwiftUI
import PDFKit
import UniformTypeIdentifiers

/// Your resume, read against your knowledge map. The original PDF is shown with every skill
/// marked green to red by how it held up when tested (neutral when never tested), above the skill
/// groups. Text is extracted on the phone with PDFKit and the server strips contact details before
/// storing it; the PDF itself stays on this phone (ResumeFileStore).
@MainActor
@Observable
final class ResumeViewModel {
    var overview: ResumeOverview?
    var isLoading = false
    var isUploading = false
    var errorMessage: String?
    /// Filter for the skill list: one of the same bands the PDF highlights use.
    var focus: ResumeStrength?

    var skills: [ResumeSkill] {
        let real = overview?.skills ?? []
        return ProcessInfo.processInfo.environment["GR_RESUME_REFERENCE"] == "1" ? Self.referenceColours(real) : real
    }

    /// UI-QA (`GR_RESUME_REFERENCE=1`): display-only colours for a reference screenshot. Most skills
    /// show as strong, some as getting there, a few as weak. Nothing is written to the server.
    private static func referenceColours(_ skills: [ResumeSkill]) -> [ResumeSkill] {
        skills.enumerated().map { index, skill in
            let bucket = index % 7
            let (status, mastery): (KnowledgeStatus, Double) =
                bucket == 3 ? (.shaky, 0.55) : bucket == 6 ? (.shaky, 0.25) : (.strong, 0.85)
            return ResumeSkill(name: skill.name, key: skill.key, section: skill.section, status: status,
                               mastery: mastery, basis: skill.basis, conceptId: skill.conceptId,
                               selfRating: skill.selfRating, spans: skill.spans)
        }
    }

    /// The original document, when this phone imported the current resume.
    var documentURL: URL? { ResumeFileStore.existingURL(for: overview?.id) }

    var documentAspectRatio: CGFloat {
        guard let url = documentURL, let doc = PDFDocument(url: url), let page = doc.page(at: 0) else { return 0.77 }
        let box = page.bounds(for: .mediaBox)
        guard box.height > 0 else { return 0.77 }
        let ratio = box.width / box.height
        return doc.pageCount > 1 ? ratio * 0.85 : ratio
    }

    /// Skills per band, in the same bands (and colours) as the marks on the PDF.
    func counts() -> [ResumeStrength: Int] {
        Dictionary(uniqueKeysWithValues: ResumeStrength.allCases.map { b in (b, skills.filter { ResumeStrength($0) == b }.count) })
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            overview = try await APIClient.shared.resumeOverview()
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "resume")
        }
    }

    func importPDF(_ url: URL) async {
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        isUploading = true
        defer { isUploading = false }
        // PDF text extraction can take a while on long files: keep it off the main actor.
        // Kept to show the original pages with their highlights. It's only sent to the server when it has no
        // text layer (a scan), to be read with OCR; the server doesn't store it.
        let original = try? Data(contentsOf: url)
        let extracted: String? = await Task.detached(priority: .userInitiated) {
            guard let doc = PDFDocument(url: url) else { return nil }
            return (0..<doc.pageCount).compactMap { doc.page(at: $0)?.string }.joined(separator: "\n")
        }.value
        guard var text = extracted else {
            errorMessage = "That file couldn't be opened as a PDF."
            return
        }
        if text.trimmingCharacters(in: .whitespacesAndNewlines).count < 50, let original {
            // A scanned or image-only PDF: the server reads it with OCR and returns the text. It keeps
            // nothing from that call; only the text is saved, as with any other resume.
            do {
                text = try await APIClient.shared.extractDocumentText(
                    data: original, filename: url.lastPathComponent, mimeType: "application/pdf"
                ).markdown
            } catch {
                errorMessage = "Couldn't read that scanned PDF: \(error.localizedDescription)"
                return
            }
        }
        guard text.trimmingCharacters(in: .whitespacesAndNewlines).count >= 50 else {
            errorMessage = "No readable text in that PDF."
            return
        }
        do {
            let uploaded = try await APIClient.shared.uploadResume(text: String(text.prefix(60000)), fileName: url.lastPathComponent)
            if let original, let id = uploaded.id {
                try? ResumeFileStore.save(original, id: id)
            }
            overview = uploaded
            errorMessage = nil
            GRHaptics.success()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "resume")
        }
    }

    /// The resume text with each skill mention tinted by its status.
    func highlighted() -> AttributedString {
        guard let text = overview?.text else { return AttributedString() }
        var attr = AttributedString(text)
        attr.foregroundColor = GRColor.textSecondary
        for skill in skills where focus == nil || ResumeStrength(skill) == focus {
            for span in skill.spans where span.count == 2 {
                // Spans are Python code-point offsets, i.e. Unicode scalar offsets (not Characters).
                let scalars = text.unicodeScalars
                guard let lo = scalars.index(scalars.startIndex, offsetBy: span[0], limitedBy: scalars.endIndex),
                      let hi = scalars.index(scalars.startIndex, offsetBy: span[1], limitedBy: scalars.endIndex),
                      lo < hi,
                      let range = Range(lo..<hi, in: attr) else { continue }
                attr[range].foregroundColor = skill.status == .unexposed ? GRColor.textPrimary : skill.status.color
                attr[range].backgroundColor = skill.status.color.opacity(skill.status == .unexposed ? 0.18 : 0.16)
                attr[range].font = .system(.body, design: .default).weight(.semibold)
            }
        }
        return attr
    }
}

struct ResumeView: View {
    @State private var model = ResumeViewModel()
    @State private var showImporter = false
    @State private var selected: KnowledgeAssessment?
    @State private var showDocument = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                GRScreenHeader(title: "Resume", subtitle: "Your claims, checked against what you know")

                if model.isUploading {
                    GlassCard {
                        HStack(spacing: 12) {
                            ProgressView().tint(GRColor.accent)
                            Text("Reading your resume and matching skills to your map…")
                                .font(GRType.body).foregroundStyle(GRColor.textSecondary)
                        }
                    }
                    .padding(.horizontal, 20)
                }

                if let err = model.errorMessage {
                    Text(err).font(GRType.caption).foregroundStyle(GRColor.warning).padding(.horizontal, 20)
                }

                if let o = model.overview, !o.isEmpty {
                    summaryCard(o).padding(.horizontal, 20)
                    if let url = model.documentURL {
                        documentCard(url: url, text: o.text ?? "").padding(.horizontal, 20)
                    } else {
                        Label("Import the PDF again on this phone to see your original pages with the skills marked.",
                              systemImage: "doc.richtext")
                            .font(GRType.caption).foregroundStyle(GRColor.textTertiary)
                            .padding(.horizontal, 20)
                    }
                    skillGroups.padding(.horizontal, 20)
                } else if !model.isLoading && !model.isUploading {
                    emptyState.padding(.horizontal, 20)
                } else if model.isLoading {
                    ProgressView().tint(GRColor.accent).frame(maxWidth: .infinity, minHeight: 160)
                }
            }
            .padding(.bottom, 32)
        }
        .background(GRColor.canvas.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if model.overview?.isEmpty == false {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showImporter = true } label: { Image(systemName: "arrow.triangle.2.circlepath.doc.on.clipboard") }
                        .accessibilityLabel("Import a newer resume")
                }
            }
        }
        .fileImporter(isPresented: $showImporter, allowedContentTypes: [.pdf]) { result in
            switch result {
            case .success(let url): Task { await model.importPDF(url) }
            case .failure(let error): model.errorMessage = APIError.userFacing(error, resource: "file")
            }
        }
        .task { await model.load() }
        .refreshable { await model.load() }
        .fullScreenCover(isPresented: $showDocument) {
            if let url = model.documentURL {
                ResumeDocumentViewer(url: url, text: model.overview?.text ?? "", skills: model.skills) { skill in
                    showDocument = false
                    open(skill)
                }
            }
        }
        .sheet(item: $selected) { a in
            KnowledgeDetailSheet(assessment: a) { _ in Task { await model.load() } }
                .presentationDetents([.medium, .large])
        }
    }

    private var emptyState: some View {
        GlassCard(cornerRadius: 22) {
            VStack(alignment: .leading, spacing: 12) {
                Image(systemName: "doc.text.magnifyingglass").font(.system(size: 30)).foregroundStyle(GRColor.accent)
                Text("See your resume the way an interviewer will test it")
                    .font(GRType.title).foregroundStyle(GRColor.textPrimary)
                Text("Import a PDF. Every skill it mentions is coloured by what GraphRecall knows about you: strong, shaky, studied but untested, or new. Skills it can't judge become quick questions.")
                    .font(GRType.body).foregroundStyle(GRColor.textSecondary)
                Label("Text is read on your phone and your PDF stays on it. Email, phone and profile links are removed before anything is stored.",
                      systemImage: "lock.shield")
                    .font(GRType.caption).foregroundStyle(GRColor.textTertiary)
                Button { showImporter = true } label: { Label("Import resume PDF", systemImage: "square.and.arrow.down") }
                    .grButton(.primary)
                    .accessibilityIdentifier("resume.import")
            }
        }
    }

    private func summaryCard(_ o: ResumeOverview) -> some View {
        let counts = model.counts()
        return GlassCard(cornerRadius: 22) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(o.fileName ?? "Resume").font(GRType.headline).foregroundStyle(GRColor.textPrimary).lineLimit(1)
                        if let d = o.createdAt {
                            Text("Imported \(d.formatted(date: .abbreviated, time: .omitted))")
                                .font(GRType.micro).foregroundStyle(GRColor.textTertiary)
                        }
                    }
                    Spacer()
                    Text("\(model.skills.count) skills").font(GRType.caption.weight(.semibold)).foregroundStyle(GRColor.textSecondary)
                }
                ResumeStrengthBar(counts: counts, total: model.skills.count)
                GRFlowLayout(spacing: 6) {
                    // Only bands that have skills: a "0" chip says nothing.
                    ForEach(ResumeStrength.allCases.filter { (counts[$0] ?? 0) > 0 }) { band in
                        GRChip(title: "\(band.title) \(counts[band] ?? 0)",
                               style: model.focus == band ? .selected : .tinted(band.tone),
                               compact: true) {
                            withAnimation(.easeOut(duration: 0.2)) { model.focus = model.focus == band ? nil : band }
                        }
                    }
                }
            }
        }
    }

    private var skillGroups: some View {
        VStack(alignment: .leading, spacing: 14) {
            ForEach(ResumeStrength.allCases) { s in
                let group = model.skills.filter { ResumeStrength($0) == s }
                if !group.isEmpty && (model.focus == nil || model.focus == s) {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 6) {
                            Circle().fill(s.color).frame(width: 8, height: 8)
                            Text(s.title.uppercased()).font(GRType.micro).foregroundStyle(s.color)
                            Text("· \(s.explanation)").font(GRType.micro).foregroundStyle(GRColor.textTertiary).lineLimit(1)
                        }
                        GRFlowLayout(spacing: 6) {
                            ForEach(group) { skill in
                                Button {
                                    open(skill)
                                } label: {
                                    Text(skill.name)
                                        .font(GRType.caption.weight(.semibold))
                                        .foregroundStyle(s == .untested ? GRColor.textPrimary : s.color)
                                        .padding(.horizontal, 10)
                                        .padding(.vertical, 6)
                                        .background(s.color.opacity(0.15), in: Capsule())
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }
            }
        }
    }

    private func open(_ skill: ResumeSkill) {
        Task {
            if let a = try? await APIClient.shared.assessKnowledge([skill.name]).first { selected = a }
        }
    }

    /// The original pages, every skill marked by strength. Tap a mark for that skill; expand to read.
    private func documentCard(url: URL, text: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                GRSectionHeader(title: "Your resume")
                Spacer()
                Button {
                    showDocument = true
                } label: {
                    Label("Full screen", systemImage: "arrow.up.left.and.arrow.down.right")
                        .font(GRType.caption.weight(.semibold))
                }
                .buttonStyle(.glass)
                .accessibilityIdentifier("resume.document.expand")
            }
            ResumeStrengthLegend(skills: model.skills)
            ResumePDFView(url: url, text: text, skills: model.skills) { open($0) }
                .aspectRatio(model.documentAspectRatio, contentMode: .fit)
                .background(Color.white)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(GRColor.stroke, lineWidth: 1))
                .accessibilityIdentifier("resume.document")
            if model.skills.allSatisfy({ ResumeStrength($0) == .untested }) {
                Text("Nothing here has been tested yet, so every mark is neutral. Skills turn green or red as you answer feed cards and quick questions on them.")
                    .font(GRType.caption).foregroundStyle(GRColor.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

}
