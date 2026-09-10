import SwiftUI

/// Inspector Quiz — calls `POST /api/feed/quiz/topic/{name}` (generates into Feed).
struct GraphQuizSheet: View {
    let topic: String
    var isDemo: Bool = false
    var onClose: () -> Void

    @State private var isGenerating = false
    @State private var didRun = false
    @State private var statusMessage: String?
    @State private var generatedCount: Int?
    @State private var errorMessage: String?
    @State private var inlineQuestions: [TopicQuizQuestion] = []
    @State private var revealed = false
    @State private var selectedOption: String?
    @State private var feedReady = false

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
        .task {
            if !didRun {
                await generate()
            }
        }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "target")
                .foregroundStyle(GRColor.accent)
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 2) {
                Text("Quiz: \(topic)")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                    .lineLimit(2)
                Text(isDemo ? "Demo · generation skipped" : "Generates practice cards into Feed")
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
            .accessibilityLabel("Close quiz")
        }
        .padding(14)
    }

    @ViewBuilder
    private var content: some View {
        VStack(alignment: .leading, spacing: 14) {
            if isGenerating {
                HStack(spacing: 10) {
                    ProgressView().tint(GRColor.accent)
                    Text("Generating quiz for \(topic)…")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                }
            } else if let errorMessage {
                Text(errorMessage)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textSecondary)
                Button {
                    Task { await generate() }
                } label: {
                    Label("Retry", systemImage: "arrow.clockwise")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.accent)
                }
                .buttonStyle(.plain)
            } else if !inlineQuestions.isEmpty {
                questionPreview(inlineQuestions[0])
                if canOpenFeed {
                    Text("Full set is queued in Feed.")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                }
            } else if let statusMessage {
                VStack(alignment: .leading, spacing: 8) {
                    Text(statusMessage)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textPrimary)
                    if let generatedCount {
                        Text("Created \(generatedCount) card\(generatedCount == 1 ? "" : "s") for Feed.")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                    }
                }
            }

            if !isGenerating {
                if canOpenFeed {
                    Button(action: openFeed) {
                        Label("Practice in Feed", systemImage: "house.fill")
                            .font(GRType.caption.weight(.semibold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 10)
                            .foregroundStyle(GRColor.canvas)
                            .background(
                                RoundedRectangle(cornerRadius: 12, style: .continuous)
                                    .fill(GRColor.accent)
                            )
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Practice quiz cards in Feed")

                    Button {
                        Task { await generate() }
                    } label: {
                        Label("Generate again", systemImage: "sparkles")
                            .font(GRType.caption.weight(.semibold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 10)
                            .foregroundStyle(GRColor.accent)
                            .background(
                                RoundedRectangle(cornerRadius: 12, style: .continuous)
                                    .stroke(GRColor.accent.opacity(0.4), lineWidth: 1)
                            )
                    }
                    .buttonStyle(.plain)
                } else {
                    Button {
                        Task { await generate() }
                    } label: {
                        Label(didRun ? "Generate again" : "Generate quiz", systemImage: "sparkles")
                            .font(GRType.caption.weight(.semibold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 10)
                            .foregroundStyle(GRColor.canvas)
                            .background(
                                RoundedRectangle(cornerRadius: 12, style: .continuous)
                                    .fill(GRColor.accent)
                            )
                    }
                    .buttonStyle(.plain)
                    .disabled(isGenerating)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func questionPreview(_ q: TopicQuizQuestion) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(q.question)
                .font(GRType.caption.weight(.medium))
                .foregroundStyle(GRColor.textPrimary)
            ForEach(Array(q.options.enumerated()), id: \.offset) { idx, opt in
                let letter = String(UnicodeScalar(65 + idx)!)
                Button {
                    selectedOption = letter
                    revealed = true
                } label: {
                    HStack {
                        Text("\(letter). \(opt)")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textSecondary)
                        Spacer()
                    }
                    .padding(10)
                    .background(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(optionFill(letter: letter, correct: q.correctAnswer))
                    )
                }
                .buttonStyle(.plain)
            }
            if revealed, let explanation = q.explanation, !explanation.isEmpty {
                Text(explanation)
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
            }
        }
    }

    private func optionFill(letter: String, correct: String?) -> Color {
        guard revealed, let selectedOption else { return GRColor.fillSubtle }
        if letter == selectedOption {
            if let correct, letter == correct { return GRColor.accent.opacity(0.25) }
            return Color.red.opacity(0.2)
        }
        if let correct, letter == correct { return GRColor.accent.opacity(0.15) }
        return GRColor.fillSubtle
    }

    private func generate() async {
        isGenerating = true
        errorMessage = nil
        statusMessage = nil
        generatedCount = nil
        inlineQuestions = []
        revealed = false
        selectedOption = nil
        feedReady = false
        defer {
            isGenerating = false
            didRun = true
        }

        if isDemo {
            statusMessage = "Demo graph — quiz generation skipped. Connect the API to generate Feed cards."
            return
        }

        do {
            let response = try await APIClient.shared.generateTopicQuiz(topic: topic)
            if let questions = response.questions, !questions.isEmpty {
                inlineQuestions = Array(questions.prefix(3))
                statusMessage = "Quiz ready"
                generatedCount = response.generated ?? response.total ?? questions.count
                notifyFeedReady()
            } else if response.status == "error" {
                errorMessage = response.error ?? "Quiz generation failed"
            } else {
                generatedCount = response.generated ?? response.total
                statusMessage = response.status == "generated"
                    ? "Quiz generated"
                    : (response.status ?? "Quiz request finished")
                // Cards land server-side even when the payload omits an inline preview.
                notifyFeedReady()
            }
        } catch {
            errorMessage = APIError.userFacing(error, resource: "quiz")
        }
    }

    /// True once generation produced Feed-bound cards (API success, not demo stub).
    private var canOpenFeed: Bool {
        !isDemo && feedReady && errorMessage == nil
    }

    private func notifyFeedReady() {
        feedReady = true
        NotificationCenter.default.post(name: .grFeedShouldReload, object: nil)
    }

    private func openFeed() {
        notifyFeedReady()
        NotificationCenter.default.post(name: .grNavigateFeed, object: nil)
        onClose()
    }
}
