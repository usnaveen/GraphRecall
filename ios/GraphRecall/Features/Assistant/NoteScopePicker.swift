import SwiftUI

/// "Notes only" scope — pick the notes the Assistant may ground its answers in.
struct NoteScopePicker: View {
    let initial: [LibraryNote]
    let onApply: ([LibraryNote]) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var notes: [LibraryNote] = []
    @State private var selectedIds: Set<String> = []
    @State private var query = ""
    @State private var isLoading = true
    @State private var message: String?

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                VStack(spacing: 12) {
                    searchField
                    if isLoading {
                        ProgressView()
                            .tint(GRColor.accent)
                            .frame(maxHeight: .infinity)
                    } else if notes.isEmpty {
                        GRBanner(systemImage: "info.circle.fill", title: message ?? "No notes yet — ingest something in Create first.", tone: .accent)
                        Spacer()
                    } else {
                        ScrollView {
                            LazyVStack(spacing: 8) {
                                ForEach(filtered) { note in
                                    row(note)
                                }
                            }
                            .padding(.bottom, 24)
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 8)
            }
            .navigationTitle("Answer from notes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                        .foregroundStyle(GRColor.textSecondary)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(selectedIds.isEmpty ? "Whole graph" : "Use \(selectedIds.count)") {
                        onApply(notes.filter { selectedIds.contains($0.id) })
                        dismiss()
                    }
                    .fontWeight(.semibold)
                    .foregroundStyle(GRColor.accent)
                }
            }
        }
        .preferredColorScheme(.dark)
        .task { await load() }
    }

    private var filtered: [LibraryNote] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return notes }
        return notes.filter {
            ($0.title ?? "").localizedCaseInsensitiveContains(q) || ($0.contentText ?? "").localizedCaseInsensitiveContains(q)
        }
    }

    private var searchField: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(GRColor.textTertiary)
            TextField("Filter notes…", text: $query)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .foregroundStyle(GRColor.textPrimary)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 11)
        .grGlassEffect(.interactive, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private func row(_ note: LibraryNote) -> some View {
        let selected = selectedIds.contains(note.id)
        return Button {
            if selected { selectedIds.remove(note.id) } else { selectedIds.insert(note.id) }
            GRHaptics.tap()
        } label: {
            HStack(spacing: 12) {
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 20))
                    .foregroundStyle(selected ? GRColor.accent : GRColor.textTertiary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(note.title?.isEmpty == false ? note.title! : "Untitled note")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                        .lineLimit(1)
                    Text(subtitle(note))
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textTertiary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .padding(12)
            .background(selected ? GRColor.accentSoft : GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func subtitle(_ note: LibraryNote) -> String {
        let kind = note.resourceType?.capitalized ?? "Note"
        let excerpt = note.contentText?
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .prefix(70) ?? ""
        return excerpt.isEmpty ? kind : "\(kind) · \(excerpt)"
    }

    private func load() async {
        selectedIds = Set(initial.map(\.id))
        defer { isLoading = false }
        guard await APIClient.shared.hasAuthToken else {
            notes = initial
            message = "Sign in to limit answers to your own notes."
            return
        }
        do {
            let fetched = try await APIClient.shared.fetchNotes(limit: 100).notes
            let fetchedIds = Set(fetched.map(\.id))
            notes = initial.filter { !fetchedIds.contains($0.id) } + fetched
        } catch {
            notes = initial
            message = APIError.userFacing(error, resource: "notes")
        }
    }
}
