import SwiftUI
import PDFKit
import UIKit

/// The original resume PDF, kept on this phone only. The server gets the extracted text (with
/// contact details stripped); the document itself never leaves the device, so the highlighted view
/// is only available on the phone that imported it.
enum ResumeFileStore {
    private static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("ResumePDFs", isDirectory: true)
    }

    private static func fileURL(for id: String) -> URL {
        let safe = id.filter { $0.isLetter || $0.isNumber || $0 == "-" }
        return directory.appendingPathComponent("\(safe).pdf")
    }

    /// Keeps only the newest resume: an older document is personal data nobody needs any more.
    static func save(_ data: Data, id: String) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: directory, withIntermediateDirectories: true)
        for old in (try? fm.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? [] {
            try? fm.removeItem(at: old)
        }
        var url = fileURL(for: id)
        try data.write(to: url, options: [.atomic, .completeFileProtection])
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? url.setResourceValues(values)
    }

    static func existingURL(for id: String?) -> URL? {
        guard let id, !id.isEmpty else { return nil }
        let url = fileURL(for: id)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    static func removeAll() {
        try? FileManager.default.removeItem(at: directory)
    }
}

/// Green-to-red by how well a skill held up when tested. A skill that was only claimed or studied
/// gets a neutral marker: colouring it green or red would claim a result that does not exist.
enum ResumeStrength: CaseIterable, Identifiable {
    case strong, okay, weak, untested

    var id: Self { self }

    init(_ skill: ResumeSkill) {
        switch skill.status {
        case .strong, .shaky:
            let m = skill.mastery ?? (skill.status == .strong ? 0.85 : 0.35)
            self = m >= 0.7 ? .strong : m >= 0.4 ? .okay : .weak
        case .seen, .unexposed:
            self = .untested
        }
    }

    var title: String {
        switch self {
        case .strong: return "Strong"
        case .okay: return "Getting there"
        case .weak: return "Weak"
        case .untested: return "Not tested yet"
        }
    }

    var uiColor: UIColor {
        switch self {
        case .strong: return UIColor(red: 0.16, green: 0.74, blue: 0.33, alpha: 1)
        case .okay: return UIColor(red: 0.98, green: 0.68, blue: 0.10, alpha: 1)
        case .weak: return UIColor(red: 0.93, green: 0.26, blue: 0.26, alpha: 1)
        // Neutral: most claims are untested, and colour should mean something (green / amber / red).
        case .untested: return UIColor(white: 0.62, alpha: 1)
        }
    }

    var color: Color { Color(uiColor: uiColor) }

    var tone: GRTone {
        switch self {
        case .strong: return .success
        case .okay: return .amber
        case .weak: return .danger
        case .untested: return .neutral
        }
    }

    var explanation: String {
        switch self {
        case .strong: return "held up when tested"
        case .okay: return "partly right when tested"
        case .weak: return "slipped when tested"
        case .untested: return "claimed or studied, not tested yet"
        }
    }

    /// Marker colour on the page: the mastery itself when tested, so 0.45 and 0.65 look different.
    static func markerColor(for skill: ResumeSkill) -> UIColor {
        let strength = ResumeStrength(skill)
        guard strength != .untested, let m = skill.mastery else { return strength.uiColor }
        return ramp(m)
    }

    /// 0 red, 0.5 amber, 1 green.
    static func ramp(_ mastery: Double) -> UIColor {
        let m = CGFloat(min(max(mastery, 0), 1))
        let red = (0.93, 0.26, 0.26), amber = (0.98, 0.68, 0.10), green = (0.16, 0.74, 0.33)
        let (a, b, t) = m < 0.5 ? (red, amber, m / 0.5) : (amber, green, (m - 0.5) / 0.5)
        return UIColor(red: a.0 + (b.0 - a.0) * t, green: a.1 + (b.1 - a.1) * t, blue: a.2 + (b.2 - a.2) * t, alpha: 1)
    }
}

/// The original pages with every skill mention marked in its strength colour. Tap a mark to see
/// what GraphRecall knows about that skill.
struct ResumePDFView: UIViewRepresentable {
    let url: URL
    let text: String
    let skills: [ResumeSkill]
    var interactive: Bool = false
    var onSelectSkill: (ResumeSkill) -> Void = { _ in }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> PDFView {
        let view = FittingPDFView()
        view.allowsZoom = interactive
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        view.pageShadowsEnabled = false
        view.backgroundColor = .clear
        view.isUserInteractionEnabled = true
        let tap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.tapped(_:)))
        tap.cancelsTouchesInView = false
        tap.delegate = context.coordinator
        view.addGestureRecognizer(tap)
        context.coordinator.pdfView = view
        return view
    }

    func updateUIView(_ view: PDFView, context: Context) {
        let coordinator = context.coordinator
        coordinator.onSelectSkill = onSelectSkill
        coordinator.skillsByKey = Dictionary(skills.map { ($0.key, $0) }, uniquingKeysWith: { a, _ in a })
        if coordinator.loadedURL != url {
            view.document = PDFDocument(url: url)
            coordinator.loadedURL = url
            coordinator.appliedSignature = nil
        }
        let signature = skills.map { "\($0.key):\($0.status.rawValue):\($0.mastery ?? -1)" }.joined(separator: "|")
        if coordinator.appliedSignature != signature, let document = view.document {
            ResumeHighlighter.apply(skills: skills, text: text, to: document)
            coordinator.appliedSignature = signature
        }
    }

    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        weak var pdfView: PDFView?
        var loadedURL: URL?
        var appliedSignature: String?
        var skillsByKey: [String: ResumeSkill] = [:]
        var onSelectSkill: (ResumeSkill) -> Void = { _ in }

        @objc func tapped(_ gesture: UITapGestureRecognizer) {
            guard let view = pdfView else { return }
            let point = gesture.location(in: view)
            guard let page = view.page(for: point, nearest: false) else { return }
            let pagePoint = view.convert(point, to: page)
            guard let annotation = page.annotations.first(where: {
                $0.userName?.hasPrefix(ResumeHighlighter.tag) == true && $0.bounds.insetBy(dx: -3, dy: -3).contains(pagePoint)
            }), let key = annotation.userName?.dropFirst(ResumeHighlighter.tag.count),
               let skill = skillsByKey[String(key)] else { return }
            GRHaptics.tap()
            onSelectSkill(skill)
        }

        func gestureRecognizer(_ g: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool {
            true
        }
    }
}

/// Fits the page to the view's width once it has a size (the fit is meaningless before layout).
/// Inline it stays fitted; full screen it can zoom in to 5x but never shrink below the fit.
final class FittingPDFView: PDFView {
    var allowsZoom = false
    private var lastFit: CGFloat = 0

    override func layoutSubviews() {
        super.layoutSubviews()
        let fit = scaleFactorForSizeToFit
        guard fit > 0, bounds.width > 0 else { return }
        minScaleFactor = fit
        maxScaleFactor = allowsZoom ? fit * 5 : fit
        if abs(fit - lastFit) > 0.0001 || scaleFactor < fit {
            lastFit = fit
            scaleFactor = fit
        }
    }
}

/// Puts the marks on the document. The words to look for are the exact mentions the server found
/// in the extracted text (its spans), so "PyTorch" is found as written; a mention must stand as a
/// whole word on the page, so the skill "C" never marks every letter c.
enum ResumeHighlighter {
    static let tag = "gr-skill:"

    static func apply(skills: [ResumeSkill], text: String, to document: PDFDocument) {
        for i in 0..<document.pageCount {
            guard let page = document.page(at: i) else { continue }
            for annotation in page.annotations where annotation.userName?.hasPrefix(tag) == true {
                page.removeAnnotation(annotation)
            }
        }
        // Longer mentions first, so "C++" and "Machine Learning" are marked before "C" or "Learning".
        let ordered = skills.sorted { (mentions(of: $0, in: text).map(\.count).max() ?? 0) > (mentions(of: $1, in: text).map(\.count).max() ?? 0) }
        var covered: [PDFPage: [CGRect]] = [:]
        for skill in ordered {
            let color = ResumeStrength.markerColor(for: skill).withAlphaComponent(0.42)
            for mention in mentions(of: skill, in: text) {
                for selection in document.findString(mention, withOptions: []) {
                    for line in selection.selectionsByLine() {
                        for page in line.pages where isWholeWord(line, on: page) {
                            let bounds = line.bounds(for: page).insetBy(dx: -0.8, dy: -0.6)
                            if covered[page, default: []].contains(where: { $0.insetBy(dx: -1, dy: -1).contains(bounds) }) { continue }
                            covered[page, default: []].append(bounds)
                            let mark = PDFAnnotation(bounds: bounds, forType: .highlight, withProperties: nil)
                            mark.color = color
                            mark.userName = tag + skill.key // no `contents`: that draws a note icon
                            page.addAnnotation(mark)
                        }
                    }
                }
            }
        }
    }

    /// The distinct ways the skill is written in the resume text (span offsets are Unicode scalar
    /// offsets, as Python counts them), or its name when the server found no mention.
    static func mentions(of skill: ResumeSkill, in text: String) -> [String] {
        let scalars = Array(text.unicodeScalars)
        var out: [String] = []
        for span in skill.spans where span.count == 2 && span[0] >= 0 && span[0] < span[1] && span[1] <= scalars.count {
            var s = String.UnicodeScalarView()
            s.append(contentsOf: scalars[span[0]..<span[1]])
            let mention = String(s).trimmingCharacters(in: .whitespacesAndNewlines)
            if !mention.isEmpty, !out.contains(mention) { out.append(mention) }
        }
        return out.isEmpty ? [skill.name] : out
    }

    private static func isWholeWord(_ selection: PDFSelection, on page: PDFPage) -> Bool {
        guard let pageString = page.string else { return true }
        let pageText = pageString as NSString
        let range = selection.range(at: 0, on: page)
        guard range.location != NSNotFound else { return true }
        func isWordCharacter(_ index: Int) -> Bool {
            guard index >= 0, index < pageText.length, let scalar = UnicodeScalar(pageText.character(at: index)) else { return false }
            return CharacterSet.alphanumerics.contains(scalar)
        }
        return !isWordCharacter(range.location - 1) && !isWordCharacter(range.location + range.length)
    }
}

/// Legend for the marks, with how many skills fall in each band.
struct ResumeStrengthLegend: View {
    let skills: [ResumeSkill]

    var body: some View {
        GRFlowLayout(spacing: 10) {
            ForEach(ResumeStrength.allCases.filter { band in skills.contains { ResumeStrength($0) == band } }) { band in
                let n = skills.filter { ResumeStrength($0) == band }.count
                HStack(spacing: 5) {
                    RoundedRectangle(cornerRadius: 3).fill(band.color.opacity(0.85)).frame(width: 14, height: 10)
                    Text("\(band.title) \(n)")
                        .font(GRType.micro)
                        .foregroundStyle(n == 0 ? GRColor.textTertiary : GRColor.textSecondary)
                }
            }
        }
    }
}

/// Full screen: the document at reading size, pinch to zoom, tap a mark for that skill.
struct ResumeDocumentViewer: View {
    let url: URL
    let text: String
    let skills: [ResumeSkill]
    var onSelectSkill: (ResumeSkill) -> Void

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(spacing: 10) {
                ResumeStrengthLegend(skills: skills)
                    .padding(.horizontal, 16)
                ResumePDFView(url: url, text: text, skills: skills, interactive: true, onSelectSkill: onSelectSkill)
                    .background(Color.white)
                    .accessibilityIdentifier("resume.document.full")
            }
            .background(GRColor.canvas.ignoresSafeArea())
            .navigationTitle("Your resume")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

/// The summary bar: one segment per band, in the PDF marks' colours.
struct ResumeStrengthBar: View {
    let counts: [ResumeStrength: Int]
    let total: Int

    var body: some View {
        GeometryReader { geo in
            HStack(spacing: 2) {
                ForEach(ResumeStrength.allCases.filter { (counts[$0] ?? 0) > 0 }) { band in
                    Capsule()
                        .fill(band.color)
                        .frame(width: max(4, geo.size.width * CGFloat(counts[band] ?? 0) / CGFloat(max(total, 1)) - 2))
                }
            }
        }
        .frame(height: 10)
        .clipShape(Capsule())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(ResumeStrength.allCases.compactMap { b in
            (counts[b] ?? 0) > 0 ? "\(b.title) \(counts[b] ?? 0)" : nil
        }.joined(separator: ", "))
    }
}
