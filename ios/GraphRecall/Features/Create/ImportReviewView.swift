import SwiftUI

/// Human-in-the-loop approval for extracted concepts (`/api/review/sessions/*`).
struct ImportReviewView: View {
    let sessionId: String
    var sourceTitle: String?
    var onFinished: (String) -> Void = { _ in }

    enum Tab: String, CaseIterable, Identifiable {
        case all = "All", matches = "Matches", low = "Low confidence"
        var id: String { rawValue }
    }

    @Environment(\.dismiss) private var dismiss
    @State private var concepts: [ConceptReviewItem] = []
    @State private var originalNames: [String: String] = [:]
    @State private var isLoading = true
    @State private var isSubmitting = false
    @State private var errorMessage: String?
    @State private var tab: Tab = .all
    @State private var editingId: String?
    @State private var confirmDiscard = false

    private var visible: [ConceptReviewItem] {
        switch tab {
        case .all: return concepts
        case .matches: return concepts.filter(\.isDuplicate)
        case .low: return concepts.filter { $0.confidence < 0.5 }
        }
    }

    private var selectedCount: Int { concepts.filter(\.isSelected).count }

    private func count(_ tab: Tab) -> Int {
        switch tab {
        case .all: return concepts.count
        case .matches: return concepts.filter(\.isDuplicate).count
        case .low: return concepts.filter { $0.confidence < 0.5 }.count
        }
    }

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(spacing: 10) {
                            Image(systemName: "sparkles")
                                .foregroundStyle(GRColor.accent)
                            Text("Nothing enters your graph until you approve. Rename, skip duplicates, or drop noise.")
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textPrimary)
                        }
                        .padding(12)
                        .background(GRColor.accentSoft, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(GRColor.accentLine, lineWidth: 1))

                        if isLoading {
                            ProgressView()
                                .tint(GRColor.accent)
                                .frame(maxWidth: .infinity, minHeight: 160)
                        } else if let errorMessage {
                            GRBanner(systemImage: "exclamationmark.triangle.fill", title: "Couldn’t load this import", subtitle: errorMessage, tone: .warning)
                        } else {
                            HStack(spacing: 6) {
                                ForEach(Tab.allCases) { item in
                                    GRChip(title: "\(item.rawValue) · \(count(item))", style: tab == item ? .selected : .plain, compact: true) {
                                        tab = item
                                    }
                                }
                            }
                            ForEach(visible) { concept in
                                if let idx = concepts.firstIndex(where: { $0.id == concept.id }) {
                                    conceptCard($concepts[idx])
                                }
                            }
                        }
                    }
                    .padding(20)
                    .padding(.bottom, 80)
                }
            }
            .navigationTitle(sourceTitle ?? "Review import")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Later") { dismiss() }
                        .foregroundStyle(GRColor.textSecondary)
                }
            }
            .safeAreaInset(edge: .bottom) {
                if !concepts.isEmpty {
                    HStack(spacing: 10) {
                        Button("Discard") { confirmDiscard = true }
                            .buttonStyle(GRButtonStyle(kind: .secondary, fullWidth: false))
                        Button {
                            Task { await approve() }
                        } label: {
                            if isSubmitting {
                                ProgressView().tint(GRColor.canvas)
                            } else {
                                Label("Approve \(selectedCount) concept\(selectedCount == 1 ? "" : "s")", systemImage: "checkmark")
                            }
                        }
                        .buttonStyle(.grPrimary)
                        .disabled(selectedCount == 0 || isSubmitting)
                    }
                    .padding(10)
                    .grGlassEffect(in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                    .padding(.horizontal, 16)
                    .padding(.bottom, 8)
                }
            }
            .confirmationDialog("Discard this import?", isPresented: $confirmDiscard, titleVisibility: .visible) {
                Button("Discard concepts", role: .destructive) {
                    Task { await discard() }
                }
            } message: {
                Text("The note is kept, but none of these concepts will be added.")
            }
        }
        .preferredColorScheme(.dark)
        .task { await load() }
    }

    private func conceptCard(_ concept: Binding<ConceptReviewItem>) -> some View {
        let item = concept.wrappedValue
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Button {
                    concept.wrappedValue.isSelected.toggle()
                    GRHaptics.tap()
                } label: {
                    GRCheckbox(isOn: item.isSelected)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(item.isSelected ? "Deselect \(item.name)" : "Select \(item.name)")

                if editingId == item.id {
                    TextField("Concept name", text: concept.name)
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                        .submitLabel(.done)
                        .onSubmit { editingId = nil }
                } else {
                    Text(item.name)
                        .font(GRType.headline)
                        .foregroundStyle(item.isSelected ? GRColor.textPrimary : GRColor.textTertiary)
                }
                Spacer(minLength: 6)
                if !item.domain.isEmpty {
                    GRChip(title: item.domain, style: .tinted(.cyan), compact: true)
                }
                Button {
                    editingId = editingId == item.id ? nil : item.id
                } label: {
                    Image(systemName: editingId == item.id ? "checkmark" : "pencil")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(GRColor.textTertiary)
                        .frame(width: 28, height: 28)
                }
                .accessibilityLabel(editingId == item.id ? "Done editing" : "Rename")
            }

            Text(item.definition)
                .font(GRType.caption)
                .foregroundStyle(item.isSelected ? GRColor.textSecondary : GRColor.textTertiary)
                .lineLimit(3)

            if !item.prerequisites.isEmpty {
                GRFlowLayout(spacing: 6, lineSpacing: 6) {
                    Text("Needs")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    ForEach(item.prerequisites.prefix(4), id: \.self) {
                        GRChip(title: $0, compact: true)
                    }
                }
            }

            if item.isDuplicate {
                VStack(alignment: .leading, spacing: 8) {
                    Label("Looks like a concept already in your graph", systemImage: "arrow.triangle.merge")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.amber)
                    HStack(spacing: 6) {
                        GRChip(title: "Keep existing", style: item.isSelected ? .outline : .selected, compact: true) {
                            concept.wrappedValue.isSelected = false
                        }
                        GRChip(title: "Add anyway", style: item.isSelected ? .selected : .outline, compact: true) {
                            concept.wrappedValue.isSelected = true
                        }
                    }
                }
                .padding(10)
                .background(GRColor.amber.opacity(0.14), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            }

            if item.confidence < 0.5 {
                Text("Low confidence · \(String(format: "%.2f", item.confidence))")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
            }
        }
        .padding(14)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(item.isDuplicate ? GRColor.amber.opacity(0.7) : .clear, lineWidth: 1)
        )
        .opacity(item.isSelected ? 1 : 0.8)
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let session = try await APIClient.shared.reviewSession(id: sessionId)
            concepts = session.concepts
            originalNames = Dictionary(session.concepts.map { ($0.id, $0.name) }, uniquingKeysWith: { first, _ in first })
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "import review")
        }
    }

    private func approve() async {
        isSubmitting = true
        defer { isSubmitting = false }
        let approved = concepts.filter(\.isSelected).map { item -> ConceptReviewItem in
            var copy = item
            if originalNames[item.id] != item.name { copy.userModified = true }
            return copy
        }
        let removed = concepts.filter { !$0.isSelected }.map(\.id)
        do {
            try await APIClient.shared.approveReviewSession(id: sessionId, approved: approved, removedIds: removed)
            GRHaptics.success()
            RecentImportsStore.shared.markReviewed(sessionId: sessionId, status: "added", detail: "\(approved.count) concepts added")
            NotificationCenter.default.post(name: .grFeedShouldReload, object: nil)
            onFinished("Added \(approved.count) concept\(approved.count == 1 ? "" : "s") to your graph.")
            dismiss()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "approval")
        }
    }

    private func discard() async {
        do {
            try await APIClient.shared.cancelReviewSession(id: sessionId)
            RecentImportsStore.shared.markReviewed(sessionId: sessionId, status: "discarded", detail: "No concepts added")
            onFinished("Import discarded — nothing was added.")
            dismiss()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "import review")
        }
    }
}
