import SwiftUI

// The knowledge map of you: every concept and skill, coloured strong / shaky / seen / new,
// with the evidence behind it. Exposure questions fill the gaps the map can't judge.

// MARK: - Shared pieces

/// A capsule split into the four statuses, proportional to their counts.
struct KnowledgeStatusBar: View {
    let counts: [KnowledgeStatus: Int]
    var height: CGFloat = 10

    private var total: Int { counts.values.reduce(0, +) }

    var body: some View {
        GeometryReader { geo in
            HStack(spacing: 2) {
                ForEach(KnowledgeStatus.allCases) { s in
                    let n = counts[s] ?? 0
                    if n > 0 {
                        Capsule()
                            .fill(s.color.opacity(s == .unexposed ? 0.45 : 0.9))
                            .frame(width: max(height, geo.size.width * CGFloat(n) / CGFloat(max(total, 1)) - 2))
                    }
                }
            }
        }
        .frame(height: height)
        .background(GRColor.fillSubtle, in: Capsule())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(KnowledgeStatus.allCases.map { "\(counts[$0] ?? 0) \($0.title)" }.joined(separator: ", "))
    }
}

struct KnowledgeStatusDot: View {
    let status: KnowledgeStatus
    var size: CGFloat = 10
    var body: some View {
        Circle().fill(status.color).frame(width: size, height: size)
            .overlay(Circle().stroke(status.color.opacity(0.35), lineWidth: 3).blur(radius: 2))
    }
}

/// "What's your exposure to X?" — five glass chips, one tap answers.
struct ExposureQuestionCard: View {
    let question: ExposureQuestion
    var onAnswered: (KnowledgeAssessment) -> Void
    var onSkip: () -> Void

    @State private var isSaving = false

    var body: some View {
        GlassCard(cornerRadius: 20) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 6) {
                    Image(systemName: "questionmark.bubble.fill").foregroundStyle(GRColor.accentCyan)
                    Text("QUICK QUESTION").font(GRType.micro).foregroundStyle(GRColor.accentCyan)
                    Spacer()
                    if !question.sourceLabel.isEmpty {
                        Text(question.sourceLabel).font(GRType.micro).foregroundStyle(GRColor.textTertiary)
                    }
                }
                Text(question.prompt)
                    .font(GRType.title)
                    .foregroundStyle(GRColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                GRFlowLayout(spacing: 8) {
                    ForEach(question.levels, id: \.level) { level in
                        GRChip(title: level.label, style: level.level == 0 ? .outline : .plain, compact: true) {
                            Task { await answer(level.level) }
                        }
                        .disabled(isSaving)
                    }
                }
                HStack {
                    Text("Your answer counts until you're tested on it.")
                        .font(GRType.micro).foregroundStyle(GRColor.textTertiary)
                    Spacer()
                    Button("Skip", action: onSkip)
                        .font(GRType.caption.weight(.semibold))
                        .buttonStyle(.borderless)
                        .tint(GRColor.textSecondary)
                }
            }
        }
    }

    private func answer(_ level: Int) async {
        isSaving = true
        defer { isSaving = false }
        GRHaptics.tap()
        if let a = try? await APIClient.shared.rateExposure(name: question.name, level: level) {
            GRHaptics.success()
            onAnswered(a)
        }
    }
}

// MARK: - Model

@MainActor
@Observable
final class KnowledgeMapViewModel {
    var summary: KnowledgeSummary?
    var questions: [ExposureQuestion] = []
    var filter: KnowledgeStatus?
    var query = ""
    var isLoading = false
    var errorMessage: String?

    var counts: [KnowledgeStatus: Int] {
        guard let s = summary else { return [:] }
        return Dictionary(uniqueKeysWithValues: KnowledgeStatus.allCases.map { ($0, s.count($0)) })
    }

    var visibleItems: [KnowledgeAssessment] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let order: [KnowledgeStatus: Int] = [.strong: 0, .shaky: 1, .seen: 2, .unexposed: 3]
        return (summary?.items ?? [])
            .filter { filter == nil || $0.status == filter }
            .filter { q.isEmpty || $0.name.lowercased().contains(q) || ($0.domain ?? "").lowercased().contains(q) }
            .sorted { (order[$0.status] ?? 9, -($0.mastery ?? 0)) < (order[$1.status] ?? 9, -($1.mastery ?? 0)) }
    }

    var domains: [(name: String, counts: [KnowledgeStatus: Int], total: Int)] {
        (summary?.domains ?? [:]).map { name, raw in
            let c = Dictionary(uniqueKeysWithValues: KnowledgeStatus.allCases.map { ($0, raw[$0.rawValue] ?? 0) })
            return (name, c, c.values.reduce(0, +))
        }
        .filter { $0.total > 0 }
        .sorted { $0.total > $1.total }
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let s = APIClient.shared.knowledgeSummary()
            async let q = APIClient.shared.exposureQuestions(limit: 8)
            summary = try await s
            questions = (try? await q) ?? []
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "knowledge map")
        }
    }

    func answered(_ a: KnowledgeAssessment) {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) { questions.removeAll { $0.name == a.name } }
        Task { summary = try? await APIClient.shared.knowledgeSummary() }
    }

    func skip(_ q: ExposureQuestion) {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.85)) { questions.removeAll { $0.id == q.id } }
    }
}

// MARK: - Screen

struct KnowledgeMapView: View {
    @State private var model = KnowledgeMapViewModel()
    @State private var selected: KnowledgeAssessment?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                GRScreenHeader(title: "Knowledge map", subtitle: "What you know, and how sure we are")

                if let summary = model.summary {
                    overview(summary).padding(.horizontal, 20)
                } else if model.isLoading {
                    ProgressView().tint(GRColor.accent).frame(maxWidth: .infinity, minHeight: 140)
                } else if let err = model.errorMessage {
                    Text(err).font(GRType.caption).foregroundStyle(GRColor.warning).padding(.horizontal, 20)
                }

                if let q = model.questions.first {
                    ExposureQuestionCard(question: q, onAnswered: model.answered, onSkip: { model.skip(q) })
                        .id(q.id)
                        .padding(.horizontal, 20)
                        .transition(.asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity),
                                                removal: .move(edge: .leading).combined(with: .opacity)))
                }

                if !model.domains.isEmpty {
                    domainsSection.padding(.horizontal, 20)
                }

                if model.summary != nil {
                    conceptsSection.padding(.horizontal, 20)
                }
            }
            .padding(.bottom, 32)
        }
        .background(GRColor.canvas.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load() }
        .refreshable { await model.load() }
        .sheet(item: $selected) { a in
            KnowledgeDetailSheet(assessment: a) { _ in Task { await model.load() } }
                .presentationDetents([.medium, .large])
        }
    }

    private func overview(_ s: KnowledgeSummary) -> some View {
        GlassCard(cornerRadius: 22) {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    Text("\(s.total)").font(.system(size: 40, weight: .bold, design: .rounded)).foregroundStyle(GRColor.textPrimary)
                    Text("concepts and skills").font(GRType.body).foregroundStyle(GRColor.textSecondary)
                    Spacer()
                }
                KnowledgeStatusBar(counts: model.counts, height: 12)
                HStack(spacing: 8) {
                    ForEach(KnowledgeStatus.allCases) { st in
                        Button {
                            withAnimation(.easeOut(duration: 0.2)) { model.filter = model.filter == st ? nil : st }
                            GRHaptics.tap()
                        } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                HStack(spacing: 5) {
                                    KnowledgeStatusDot(status: st, size: 8)
                                    Text(st.shortTitle).font(GRType.micro).foregroundStyle(GRColor.textSecondary).lineLimit(1)
                                }
                                Text("\(s.count(st))").font(GRType.headline).foregroundStyle(GRColor.textPrimary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(10)
                            .background(model.filter == st ? st.color.opacity(0.18) : GRColor.fillSubtle,
                                        in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(s.count(st)) \(st.title). \(st.explanation)")
                    }
                }
                if let f = model.filter {
                    Text(f.explanation).font(GRType.caption).foregroundStyle(f.color)
                }
            }
        }
    }

    private var domainsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: "By area")
            VStack(spacing: 10) {
                ForEach(model.domains.prefix(8), id: \.name) { d in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text(d.name).font(GRType.caption.weight(.semibold)).foregroundStyle(GRColor.textPrimary).lineLimit(1)
                            Spacer()
                            Text("\(d.counts[.strong] ?? 0) strong of \(d.total)").font(GRType.micro).foregroundStyle(GRColor.textTertiary)
                        }
                        KnowledgeStatusBar(counts: d.counts, height: 7)
                    }
                }
            }
            .padding(14)
            .grGlassEffect(in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
    }

    private var conceptsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            GRSectionHeader(title: model.filter.map { "\($0.title) (\(model.visibleItems.count))" } ?? "Everything")
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass").foregroundStyle(GRColor.textTertiary)
                TextField("Search concepts or areas", text: $model.query)
                    .textInputAutocapitalization(.never)
                    .foregroundStyle(GRColor.textPrimary)
            }
            .padding(12)
            .grGlassEffect(in: Capsule())
            LazyVStack(spacing: 8) {
                ForEach(model.visibleItems.prefix(200)) { a in
                    Button { selected = a } label: { row(a) }.buttonStyle(.plain)
                }
            }
        }
    }

    private func row(_ a: KnowledgeAssessment) -> some View {
        HStack(spacing: 12) {
            KnowledgeStatusDot(status: a.status)
            VStack(alignment: .leading, spacing: 2) {
                Text(a.name).font(GRType.headline).foregroundStyle(GRColor.textPrimary).lineLimit(1)
                Text(a.basisLabel).font(GRType.caption).foregroundStyle(GRColor.textSecondary).lineLimit(1)
            }
            Spacer(minLength: 8)
            if let m = a.mastery, a.status != .unexposed {
                Text("\(Int((m * 100).rounded()))%")
                    .font(GRType.caption.weight(.semibold).monospacedDigit())
                    .foregroundStyle(a.status.color)
            }
        }
        .padding(.vertical, 11)
        .padding(.horizontal, 14)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

// MARK: - Detail

struct KnowledgeDetailSheet: View {
    let assessment: KnowledgeAssessment
    var onChange: ((KnowledgeAssessment) -> Void)? = nil

    @Environment(\.dismiss) private var dismiss
    @State private var current: KnowledgeAssessment?
    @State private var isSaving = false

    private var a: KnowledgeAssessment { current ?? assessment }
    private let levels = ["Never", "Heard of it", "Know the basics", "Used it", "Strong"]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 10) {
                        Image(systemName: a.status.systemImage).font(.title2).foregroundStyle(a.status.color)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(a.status.title.uppercased()).font(GRType.micro).foregroundStyle(a.status.color)
                            Text(a.name).font(GRType.title).foregroundStyle(GRColor.textPrimary)
                        }
                    }
                    Text(a.status.explanation).font(GRType.body).foregroundStyle(GRColor.textSecondary)

                    if let m = a.mastery, a.status != .unexposed {
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text("Estimated mastery").font(GRType.caption).foregroundStyle(GRColor.textSecondary)
                                Spacer()
                                Text("\(Int((m * 100).rounded()))%").font(GRType.headline.monospacedDigit()).foregroundStyle(a.status.color)
                            }
                            GRProgressBar(value: m, tint: a.status.color)
                            if let c = a.confidence {
                                Text("Confidence \(Int((c * 100).rounded()))%: more evidence, more confidence.")
                                    .font(GRType.micro).foregroundStyle(GRColor.textTertiary)
                            }
                        }
                        .padding(14)
                        .grGlassEffect(in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }

                    VStack(alignment: .leading, spacing: 6) {
                        Text("EVIDENCE").font(GRType.micro).foregroundStyle(GRColor.textTertiary)
                        Text(a.evidenceSummary).font(GRType.body).foregroundStyle(GRColor.textPrimary)
                        Text(a.basisLabel).font(GRType.caption).foregroundStyle(GRColor.textSecondary)
                        if let d = a.domain { Text("Area: \(d)").font(GRType.caption).foregroundStyle(GRColor.textSecondary) }
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        Text("HOW WELL DO YOU KNOW IT?").font(GRType.micro).foregroundStyle(GRColor.textTertiary)
                        GRFlowLayout(spacing: 8) {
                            ForEach(0..<5, id: \.self) { i in
                                GRChip(title: levels[i], style: a.selfRating == i ? .selected : .plain, compact: true) {
                                    Task { await rate(i) }
                                }
                                .disabled(isSaving)
                            }
                        }
                        Text("Reviews and quizzes outweigh this as soon as you're tested.")
                            .font(GRType.micro).foregroundStyle(GRColor.textTertiary)
                    }
                }
                .padding(20)
            }
            .background(GRColor.canvas.ignoresSafeArea())
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
        }
        .preferredColorScheme(.dark)
        .tint(GRColor.accent)
    }

    private func rate(_ level: Int) async {
        isSaving = true
        defer { isSaving = false }
        GRHaptics.tap()
        if let updated = try? await APIClient.shared.rateExposure(name: a.name, level: level) {
            withAnimation(.easeOut(duration: 0.2)) { current = updated }
            GRHaptics.success()
            onChange?(updated)
        }
    }
}
