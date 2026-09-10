import SwiftUI

@MainActor
@Observable
final class CreateViewModel {
    var text: String = ""
    var isSubmitting = false
    var errorMessage: String?
    var lastResponse: ConceptDumpResponse?

    var parsedConcepts: [String] {
        text
            .split(whereSeparator: { $0 == "\n" || $0 == "," || $0 == ";" })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    var canSubmit: Bool {
        !isSubmitting && !parsedConcepts.isEmpty
    }

    func submit() async {
        let concepts = parsedConcepts
        guard !concepts.isEmpty else {
            errorMessage = "Add at least one concept."
            return
        }
        isSubmitting = true
        errorMessage = nil
        defer { isSubmitting = false }
        do {
            let response = try await APIClient.shared.dumpConcepts(concepts)
            lastResponse = response
            await OfflineReviewStore.shared.ingestDump(response)
            NotificationCenter.default.post(name: .grDumpCompleted, object: nil)
        } catch {
            errorMessage = error.localizedDescription
            lastResponse = nil
        }
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
                        subtitle: "Dump concepts to research — teach cards land in your feed"
                    )

                    GlassCard {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Concept dump")
                                .font(GRType.headline)
                                .foregroundStyle(GRColor.textPrimary)
                            Text("One per line (or commas). We'll pull Wikipedia/articles and build cards.")
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textSecondary)

                            TextEditor(text: $model.text)
                                .frame(minHeight: 140)
                                .scrollContentBackground(.hidden)
                                .padding(10)
                                .background(
                                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                                        .fill(GRColor.fillSubtle)
                                )
                                .foregroundStyle(GRColor.textPrimary)
                                .font(GRType.body)

                            if !model.parsedConcepts.isEmpty {
                                Text("\(model.parsedConcepts.count) concepts ready")
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.accent)
                            }

                            Button {
                                Task { await model.submit() }
                            } label: {
                                HStack {
                                    if model.isSubmitting { ProgressView().tint(.black) }
                                    Text(model.isSubmitting ? "Researching…" : "Research & add to feed")
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
                    }
                    .padding(.horizontal, 20)

                    if let err = model.errorMessage {
                        Text(err)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.warning)
                            .padding(.horizontal, 20)
                    }

                    if let response = model.lastResponse {
                        resultsSection(response)
                            .padding(.horizontal, 20)
                    }
                }
                .padding(.bottom, GRLayout.dockClearance)
            }
        }
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
    private func resultsSection(_ response: ConceptDumpResponse) -> some View {
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
}

#Preview { CreateView().preferredColorScheme(.dark) }
