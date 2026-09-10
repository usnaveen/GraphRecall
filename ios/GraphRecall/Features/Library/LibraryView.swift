import SwiftUI

@MainActor
@Observable
final class LibraryViewModel {
    var books: [LibraryNote] = []
    var searchQuery: String = ""
    var isLoading = false
    var errorMessage: String?

    var filtered: [LibraryNote] {
        let q = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return books }
        return books.filter { book in
            book.displayTitle.lowercased().contains(q)
                || (book.contentText?.lowercased().contains(q) ?? false)
        }
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await APIClient.shared.fetchLibraryBooks()
            books = response.notes
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "library")
        }
    }
}

struct LibraryView: View {
    @State private var model = LibraryViewModel()

    var body: some View {
        ZStack {
            Circle()
                .fill(GRColor.accent.opacity(0.10))
                .frame(width: 240, height: 240)
                .blur(radius: 50)
                .offset(x: 110, y: -160)
                .allowsHitTesting(false)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    GRScreenHeader(
                        title: "Library",
                        subtitle: "\(model.books.count) \(model.books.count == 1 ? "book" : "books") ingested"
                    )

                    searchField
                        .padding(.horizontal, 20)

                    if model.isLoading && model.books.isEmpty {
                        ProgressView()
                            .tint(GRColor.accent)
                            .frame(maxWidth: .infinity, minHeight: 120)
                    } else if let err = model.errorMessage, model.books.isEmpty {
                        Text(err)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.warning)
                            .padding(.horizontal, 20)
                    } else if model.filtered.isEmpty {
                        emptyState
                            .padding(.horizontal, 20)
                    } else {
                        LazyVStack(spacing: 12) {
                            ForEach(model.filtered) { book in
                                NavigationLink(value: book) {
                                    BookCardRow(book: book)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(.horizontal, 20)
                    }
                }
                .padding(.bottom, GRLayout.dockClearance)
            }
        }
        .navigationDestination(for: LibraryNote.self) { book in
            BookDetailView(book: book)
        }
        .task { await model.load() }
        .refreshable { await model.load() }
    }

    private var searchField: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(GRColor.textTertiary)
            TextField("Search books…", text: $model.searchQuery)
                .foregroundStyle(GRColor.textPrimary)
                .font(GRType.body)
                .autocorrectionDisabled()
            if !model.searchQuery.isEmpty {
                Button {
                    model.searchQuery = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(GRColor.textTertiary)
                }
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(GRColor.fillSubtle)
        )
    }

    private var emptyState: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                Text(model.searchQuery.isEmpty ? "No books yet" : "No matches")
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                Text(
                    model.searchQuery.isEmpty
                        ? "Ingest a processed ZIP from Create → File, or mark content as resource_type=book."
                        : "Try a different search."
                )
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
            }
        }
    }
}

struct BookCardRow: View {
    let book: LibraryNote

    var body: some View {
        GlassCard(cornerRadius: 16) {
            HStack(alignment: .top, spacing: 14) {
                bookCover(title: book.displayTitle, height: 88)
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .top) {
                        Text(book.displayTitle)
                            .font(GRType.headline)
                            .foregroundStyle(GRColor.textPrimary)
                            .lineLimit(2)
                        Spacer(minLength: 4)
                        Image(systemName: "chevron.right")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(GRColor.textTertiary)
                    }
                    Text(previewText)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                        .lineLimit(2)
                    HStack(spacing: 10) {
                        meta(icon: "doc.text", text: "\(book.wordCount) words")
                        meta(icon: "clock", text: "~\(book.estimatedReadTime)")
                        if !book.chapters.isEmpty {
                            meta(icon: "list.bullet", text: "\(book.chapters.count) sections")
                        }
                    }
                }
            }
        }
    }

    private var previewText: String {
        let raw = book.contentText ?? ""
        if raw.isEmpty { return "No content preview" }
        return String(raw.prefix(150))
    }

    private func meta(icon: String, text: String) -> some View {
        HStack(spacing: 3) {
            Image(systemName: icon)
                .font(.system(size: 9, weight: .semibold))
            Text(text)
                .font(GRType.micro)
        }
        .foregroundStyle(GRColor.textTertiary)
    }
}

struct BookDetailView: View {
    let book: LibraryNote
    @State private var section: DetailSection = .overview

    private enum DetailSection: String, CaseIterable, Identifiable {
        case overview, chapters, content
        var id: String { rawValue }
        var title: String { rawValue.capitalized }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                hero
                    .padding(.horizontal, 20)

                sectionPicker
                    .padding(.horizontal, 20)

                Group {
                    switch section {
                    case .overview: overviewBody
                    case .chapters: chaptersBody
                    case .content: contentBody
                    }
                }
                .padding(.horizontal, 20)
            }
            .padding(.bottom, GRLayout.dockClearance)
        }
        .background(GRColor.canvas.ignoresSafeArea())
        .navigationTitle(book.displayTitle)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var hero: some View {
        GlassCard {
            HStack(alignment: .top, spacing: 14) {
                bookCover(title: book.displayTitle, height: 128)
                VStack(alignment: .leading, spacing: 10) {
                    Text(book.displayTitle)
                        .font(GRType.title)
                        .foregroundStyle(GRColor.textPrimary)
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                        statBox("Words", "\(book.wordCount)")
                        statBox("Read", "~\(book.estimatedReadTime)")
                        statBox("Sections", "\(book.chapters.count)")
                        statBox("Added", shortDate)
                    }
                }
            }
        }
    }

    private var sectionPicker: some View {
        HStack(spacing: 6) {
            ForEach(DetailSection.allCases) { tab in
                Button {
                    section = tab
                } label: {
                    Text(tab.title)
                        .font(GRType.caption)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                        .foregroundStyle(section == tab ? GRColor.accent : GRColor.textSecondary)
                        .background {
                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                .fill(section == tab ? GRColor.accent.opacity(0.18) : Color.clear)
                        }
                }
                .buttonStyle(.plain)
            }
        }
        .padding(4)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(GRColor.fillSubtle)
        )
    }

    private var overviewBody: some View {
        VStack(alignment: .leading, spacing: 12) {
            GlassCard {
                VStack(alignment: .leading, spacing: 8) {
                    Text("PREVIEW")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    Text(preview)
                        .font(GRType.body)
                        .foregroundStyle(GRColor.textSecondary)
                }
            }
            GlassCard {
                VStack(alignment: .leading, spacing: 8) {
                    Text("DETAILS")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    HStack(spacing: 8) {
                        badge(book.resourceType ?? "book", tint: GRColor.accent)
                        badge("\((book.contentText ?? "").count) chars", tint: GRColor.textSecondary)
                    }
                    if let urlStr = book.sourceURL, let url = URL(string: urlStr) {
                        Link("Source link", destination: url)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.accentCyan)
                    }
                }
            }
        }
    }

    private var chaptersBody: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 10) {
                if book.chapters.isEmpty {
                    Text("No chapter headings found in this book.")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                } else {
                    ForEach(Array(book.chapters.enumerated()), id: \.offset) { idx, chapter in
                        HStack(alignment: .top, spacing: 10) {
                            Text(String(format: "%02d", idx + 1))
                                .font(GRType.micro)
                                .foregroundStyle(GRColor.accent)
                                .frame(width: 24, alignment: .leading)
                            Text(chapter)
                                .font(GRType.body)
                                .foregroundStyle(GRColor.textPrimary)
                        }
                        if idx < book.chapters.count - 1 {
                            Divider().overlay(GRColor.stroke)
                        }
                    }
                }
            }
        }
    }

    private var contentBody: some View {
        GlassCard {
            Text(book.contentText?.isEmpty == false ? (book.contentText ?? "") : "No content available")
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
                .textSelection(.enabled)
        }
    }

    private var preview: String {
        let raw = book.contentText ?? ""
        if raw.isEmpty { return "No content available" }
        if raw.count > 800 { return String(raw.prefix(800)) + "…" }
        return raw
    }

    private var shortDate: String {
        guard let raw = book.createdAt else { return "—" }
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = iso.date(from: raw)
            ?? ISO8601DateFormatter().date(from: raw)
        guard let date else {
            return String(raw.prefix(10))
        }
        let f = DateFormatter()
        f.dateFormat = "MMM d"
        return f.string(from: date)
    }

    private func statBox(_ label: String, _ value: String) -> some View {
        VStack(spacing: 2) {
            Text(label)
                .font(GRType.micro)
                .foregroundStyle(GRColor.textTertiary)
            Text(value)
                .font(GRType.caption)
                .foregroundStyle(GRColor.textPrimary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity)
        .padding(8)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(GRColor.fillSubtle)
        )
    }

    private func badge(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(GRType.micro)
            .foregroundStyle(tint)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(
                Capsule(style: .continuous)
                    .fill(tint.opacity(0.12))
            )
    }
}

@ViewBuilder
func bookCover(title: String, height: CGFloat) -> some View {
    let hash = title.unicodeScalars.reduce(0) { $0 + Int($1.value) }
    let hue1 = Double(hash % 360) / 360.0
    let hue2 = Double((hash + 40) % 360) / 360.0
    let c1 = Color(hue: hue1, saturation: 0.60, brightness: 0.35)
    let c2 = Color(hue: hue2, saturation: 0.50, brightness: 0.22)

    ZStack(alignment: .bottom) {
        RoundedRectangle(cornerRadius: 10, style: .continuous)
            .fill(
                LinearGradient(colors: [c1, c2], startPoint: .topLeading, endPoint: .bottomTrailing)
            )
        LinearGradient(colors: [.clear, .black.opacity(0.35)], startPoint: .top, endPoint: .bottom)
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        Image(systemName: "bookmark.fill")
            .font(.system(size: height > 100 ? 22 : 16))
            .foregroundStyle(.white.opacity(0.4))
            .padding(.bottom, 10)
        // Spine
        HStack {
            Rectangle()
                .fill(Color.white.opacity(0.12))
                .frame(width: 3)
            Spacer(minLength: 0)
        }
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
    .frame(width: height * 0.72, height: height)
}
