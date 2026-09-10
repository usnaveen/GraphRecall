import SwiftUI

// MARK: - Shared helpers

enum ProfileDateFormat {
    static func short(_ raw: String?) -> String {
        guard let raw, !raw.isEmpty else { return "" }
        let key = raw.split(separator: "T").first.map(String.init) ?? raw
        let inF = DateFormatter()
        inF.locale = Locale(identifier: "en_US_POSIX")
        inF.timeZone = TimeZone(secondsFromGMT: 0)
        inF.dateFormat = "yyyy-MM-dd"
        guard let date = inF.date(from: String(key.prefix(10))) else {
            return String(key.prefix(10))
        }
        let out = DateFormatter()
        out.locale = Locale(identifier: "en_US")
        out.dateStyle = .medium
        out.timeStyle = .none
        return out.string(from: date)
    }
}

private struct ProfileListSearchField: View {
    @Binding var query: String
    var placeholder: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(GRColor.textTertiary)
            TextField(placeholder, text: $query)
                .foregroundStyle(GRColor.textPrimary)
                .font(GRType.body)
                .autocorrectionDisabled()
            if !query.isEmpty {
                Button {
                    query = ""
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
}

private struct ProfileSoftEmpty: View {
    let icon: String
    let title: String
    let message: String

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 8) {
                Image(systemName: icon)
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(GRColor.textTertiary)
                Text(title)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                Text(message)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textSecondary)
            }
        }
    }
}

// MARK: - Notes

@MainActor
@Observable
final class ProfileNotesViewModel {
    var notes: [LibraryNote] = []
    var searchQuery = ""
    var isLoading = false
    var errorMessage: String?

    var filtered: [LibraryNote] {
        let q = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return notes }
        return notes.filter {
            ($0.title ?? "").lowercased().contains(q)
                || ($0.contentText ?? "").lowercased().contains(q)
        }
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await APIClient.shared.fetchNotes(limit: 100)
            // Exclude books — those live in Library (NAV-31).
            notes = response.notes.filter {
                ($0.resourceType ?? "").lowercased() != "book"
            }
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "notes")
        }
    }
}

struct ProfileNotesListView: View {
    @State private var model = ProfileNotesViewModel()
    @State private var selected: LibraryNote?

    var body: some View {
        ZStack {
            glow
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    GRScreenHeader(
                        title: "My Notes",
                        subtitle: "\(model.notes.count) total"
                    )
                    ProfileListSearchField(query: $model.searchQuery, placeholder: "Search notes…")
                        .padding(.horizontal, 20)

                    if model.isLoading && model.notes.isEmpty {
                        ProgressView().tint(GRColor.accent)
                            .frame(maxWidth: .infinity, minHeight: 120)
                    } else if let err = model.errorMessage, model.notes.isEmpty {
                        Text(err)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.warning)
                            .padding(.horizontal, 20)
                    } else if model.filtered.isEmpty {
                        ProfileSoftEmpty(
                            icon: "doc.text",
                            title: model.searchQuery.isEmpty ? "No notes yet" : "No matches",
                            message: model.searchQuery.isEmpty
                                ? "Start adding notes from Create."
                                : "Try a different search."
                        )
                        .padding(.horizontal, 20)
                    } else {
                        LazyVStack(spacing: 10) {
                            ForEach(model.filtered) { note in
                                Button { selected = note } label: {
                                    noteRow(note)
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
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load() }
        .refreshable { await model.load() }
        .sheet(item: $selected) { note in
            NavigationStack {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(noteTitle(note))
                            .font(GRType.title)
                            .foregroundStyle(GRColor.textPrimary)
                        HStack(spacing: 8) {
                            if let d = note.createdAt {
                                Text(ProfileDateFormat.short(d))
                                    .font(GRType.micro)
                                    .foregroundStyle(GRColor.textTertiary)
                            }
                            if let t = note.resourceType, !t.isEmpty {
                                Text(t)
                                    .font(GRType.micro)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 3)
                                    .background(Capsule().fill(GRColor.fillSubtle))
                                    .foregroundStyle(GRColor.textSecondary)
                            }
                        }
                        Text(note.contentText ?? "No content available")
                            .font(GRType.body)
                            .foregroundStyle(GRColor.textSecondary)
                    }
                    .padding(20)
                }
                .background(GRColor.canvas.ignoresSafeArea())
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("Done") { selected = nil }
                            .foregroundStyle(GRColor.accent)
                    }
                }
            }
            .preferredColorScheme(.dark)
            .presentationDetents([.medium, .large])
        }
    }

    private var glow: some View {
        Circle()
            .fill(GRColor.accentCyan.opacity(0.10))
            .frame(width: 220, height: 220)
            .blur(radius: 50)
            .offset(x: -90, y: -150)
            .allowsHitTesting(false)
    }

    private func noteTitle(_ note: LibraryNote) -> String {
        let t = note.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return t.isEmpty ? "Untitled Note" : t
    }

    private func noteRow(_ note: LibraryNote) -> some View {
        GlassCard(cornerRadius: 16) {
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(GRColor.accentCyan.opacity(0.15))
                        .frame(width: 36, height: 36)
                    Image(systemName: "doc.text.fill")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(GRColor.accentCyan)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(noteTitle(note))
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                        .lineLimit(1)
                    Text(String((note.contentText ?? "No content").prefix(120)))
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)
                        .lineLimit(2)
                    HStack(spacing: 8) {
                        if let d = note.createdAt {
                            Label(ProfileDateFormat.short(d), systemImage: "clock")
                                .font(GRType.micro)
                                .foregroundStyle(GRColor.textTertiary)
                        }
                        if let t = note.resourceType, !t.isEmpty {
                            Text(t)
                                .font(GRType.micro)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Capsule().fill(GRColor.fillSubtle))
                                .foregroundStyle(GRColor.textTertiary)
                        }
                    }
                }
                Spacer(minLength: 0)
            }
        }
    }
}

// MARK: - Concepts

@MainActor
@Observable
final class ProfileConceptsViewModel {
    var concepts: [ProfileConcept] = []
    var searchQuery = ""
    var selectedDomain: String?
    var isLoading = false
    var errorMessage: String?

    var domains: [String] {
        Array(Set(concepts.map(\.domain).filter { !$0.isEmpty })).sorted()
    }

    var filtered: [ProfileConcept] {
        let q = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return concepts.filter { c in
            let matchQ = q.isEmpty
                || c.name.lowercased().contains(q)
                || c.definition.lowercased().contains(q)
            let matchD = selectedDomain == nil || c.domain == selectedDomain
            return matchQ && matchD
        }
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            concepts = try await APIClient.shared.fetchProfileConcepts()
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "concepts")
        }
    }
}

struct ProfileConceptsListView: View {
    @State private var model = ProfileConceptsViewModel()

    var body: some View {
        ZStack {
            Circle()
                .fill(GRColor.accent.opacity(0.10))
                .frame(width: 220, height: 220)
                .blur(radius: 50)
                .offset(x: 100, y: -150)
                .allowsHitTesting(false)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    GRScreenHeader(
                        title: "My Concepts",
                        subtitle: "\(model.concepts.count) total"
                    )
                    ProfileListSearchField(query: $model.searchQuery, placeholder: "Search concepts…")
                        .padding(.horizontal, 20)

                    if !model.domains.isEmpty {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 8) {
                                domainChip("All", selected: model.selectedDomain == nil) {
                                    model.selectedDomain = nil
                                }
                                ForEach(model.domains, id: \.self) { domain in
                                    domainChip(domain, selected: model.selectedDomain == domain) {
                                        model.selectedDomain = model.selectedDomain == domain ? nil : domain
                                    }
                                }
                            }
                            .padding(.horizontal, 20)
                        }
                    }

                    if model.isLoading && model.concepts.isEmpty {
                        ProgressView().tint(GRColor.accent)
                            .frame(maxWidth: .infinity, minHeight: 120)
                    } else if let err = model.errorMessage, model.concepts.isEmpty {
                        Text(err)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.warning)
                            .padding(.horizontal, 20)
                    } else if model.filtered.isEmpty {
                        ProfileSoftEmpty(
                            icon: "brain.head.profile",
                            title: model.searchQuery.isEmpty && model.selectedDomain == nil
                                ? "No concepts yet"
                                : "No matches",
                            message: "Ingest notes to grow your knowledge graph."
                        )
                        .padding(.horizontal, 20)
                    } else {
                        LazyVStack(spacing: 10) {
                            ForEach(model.filtered) { concept in
                                GlassCard(cornerRadius: 16) {
                                    HStack(alignment: .top, spacing: 12) {
                                        ZStack {
                                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                                .fill(GRColor.accent.opacity(0.15))
                                                .frame(width: 36, height: 36)
                                            Image(systemName: "brain.head.profile")
                                                .font(.system(size: 14, weight: .semibold))
                                                .foregroundStyle(GRColor.accent)
                                        }
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(concept.name)
                                                .font(GRType.headline)
                                                .foregroundStyle(GRColor.textPrimary)
                                                .lineLimit(1)
                                            Text(concept.definition.isEmpty ? "No definition" : concept.definition)
                                                .font(GRType.caption)
                                                .foregroundStyle(GRColor.textSecondary)
                                                .lineLimit(2)
                                            HStack(spacing: 8) {
                                                Text(concept.domain)
                                                    .font(GRType.micro)
                                                    .padding(.horizontal, 6)
                                                    .padding(.vertical, 2)
                                                    .background(Capsule().fill(GRColor.accent.opacity(0.12)))
                                                    .foregroundStyle(GRColor.accent)
                                                Text("Complexity \(concept.complexityScore)/10")
                                                    .font(GRType.micro)
                                                    .foregroundStyle(GRColor.textTertiary)
                                            }
                                        }
                                        Spacer(minLength: 0)
                                    }
                                }
                            }
                        }
                        .padding(.horizontal, 20)
                    }
                }
                .padding(.bottom, GRLayout.dockClearance)
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load() }
        .refreshable { await model.load() }
    }

    private func domainChip(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(GRType.caption)
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .foregroundStyle(selected ? GRColor.canvas : GRColor.textSecondary)
                .background(
                    Capsule().fill(selected ? GRColor.accent : GRColor.fillSubtle)
                )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Uploads / Resources

@MainActor
@Observable
final class ProfileUploadsViewModel {
    var uploads: [ProfileUpload] = []
    var searchQuery = ""
    var isLoading = false
    var errorMessage: String?

    var filtered: [ProfileUpload] {
        let q = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !q.isEmpty else { return uploads }
        return uploads.filter {
            $0.displayTitle.lowercased().contains(q)
                || ($0.description ?? "").lowercased().contains(q)
                || ($0.fileURL ?? "").lowercased().contains(q)
        }
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await APIClient.shared.fetchUploads(limit: 50)
            uploads = response.uploads
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "uploads")
        }
    }
}

struct ProfileUploadsListView: View {
    @State private var model = ProfileUploadsViewModel()
    private let accent = Color(red: 1.0, green: 0.42, blue: 0.42)

    var body: some View {
        ZStack {
            Circle()
                .fill(accent.opacity(0.12))
                .frame(width: 220, height: 220)
                .blur(radius: 50)
                .offset(x: -80, y: -140)
                .allowsHitTesting(false)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    GRScreenHeader(
                        title: "My Uploads",
                        subtitle: "\(model.uploads.count) total"
                    )
                    ProfileListSearchField(query: $model.searchQuery, placeholder: "Search uploads…")
                        .padding(.horizontal, 20)

                    if model.isLoading && model.uploads.isEmpty {
                        ProgressView().tint(accent)
                            .frame(maxWidth: .infinity, minHeight: 120)
                    } else if let err = model.errorMessage, model.uploads.isEmpty {
                        Text(err)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.warning)
                            .padding(.horizontal, 20)
                    } else if model.filtered.isEmpty {
                        ProfileSoftEmpty(
                            icon: "photo.on.rectangle",
                            title: model.searchQuery.isEmpty ? "No uploads yet" : "No matches",
                            message: "Add a screenshot from Create to see it here."
                        )
                        .padding(.horizontal, 20)
                    } else {
                        LazyVStack(spacing: 10) {
                            ForEach(model.filtered) { upload in
                                GlassCard(cornerRadius: 16) {
                                    HStack(alignment: .top, spacing: 12) {
                                        ZStack {
                                            RoundedRectangle(cornerRadius: 10, style: .continuous)
                                                .fill(accent.opacity(0.15))
                                                .frame(width: 36, height: 36)
                                            Image(systemName: "photo.fill")
                                                .font(.system(size: 14, weight: .semibold))
                                                .foregroundStyle(accent)
                                        }
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(upload.displayTitle)
                                                .font(GRType.headline)
                                                .foregroundStyle(GRColor.textPrimary)
                                                .lineLimit(1)
                                            if let desc = upload.description, !desc.isEmpty {
                                                Text(desc)
                                                    .font(GRType.caption)
                                                    .foregroundStyle(GRColor.textSecondary)
                                                    .lineLimit(2)
                                            }
                                            HStack(spacing: 8) {
                                                if let d = upload.createdAt {
                                                    Label(ProfileDateFormat.short(d), systemImage: "clock")
                                                        .font(GRType.micro)
                                                        .foregroundStyle(GRColor.textTertiary)
                                                }
                                                if let t = upload.uploadType, !t.isEmpty {
                                                    Text(t)
                                                        .font(GRType.micro)
                                                        .padding(.horizontal, 6)
                                                        .padding(.vertical, 2)
                                                        .background(Capsule().fill(GRColor.fillSubtle))
                                                        .foregroundStyle(GRColor.textTertiary)
                                                }
                                            }
                                        }
                                        Spacer(minLength: 0)
                                    }
                                }
                            }
                        }
                        .padding(.horizontal, 20)
                    }
                }
                .padding(.bottom, GRLayout.dockClearance)
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load() }
        .refreshable { await model.load() }
    }
}

// MARK: - Quiz history

@MainActor
@Observable
final class ProfileQuizzesViewModel {
    var quizzes: [QuizHistoryItem] = []
    var openTopic: String?
    var isLoading = false
    var errorMessage: String?

    var grouped: [(topic: String, items: [QuizHistoryItem])] {
        var map: [String: [QuizHistoryItem]] = [:]
        for q in quizzes {
            map[q.topicKey, default: []].append(q)
        }
        return map.keys.sorted().map { ($0, map[$0] ?? []) }
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await APIClient.shared.fetchQuizHistory()
            quizzes = response.quizzes
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "quizzes")
        }
    }
}

struct ProfileQuizzesListView: View {
    @State private var model = ProfileQuizzesViewModel()

    var body: some View {
        ZStack {
            Circle()
                .fill(Color(red: 0.61, green: 0.35, blue: 0.71).opacity(0.15))
                .frame(width: 220, height: 220)
                .blur(radius: 50)
                .offset(x: 90, y: -140)
                .allowsHitTesting(false)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    GRScreenHeader(
                        title: "Quiz History",
                        subtitle: "\(model.quizzes.count) questions"
                    )

                    if model.isLoading && model.quizzes.isEmpty {
                        ProgressView().tint(GRColor.accent)
                            .frame(maxWidth: .infinity, minHeight: 120)
                    } else if let err = model.errorMessage, model.quizzes.isEmpty {
                        Text(err)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.warning)
                            .padding(.horizontal, 20)
                    } else if model.grouped.isEmpty {
                        ProfileSoftEmpty(
                            icon: "questionmark.circle",
                            title: "No quizzes yet",
                            message: "Complete reviews in Feed to build history."
                        )
                        .padding(.horizontal, 20)
                    } else {
                        LazyVStack(spacing: 12) {
                            ForEach(model.grouped, id: \.topic) { group in
                                topicSection(group.topic, items: group.items)
                            }
                        }
                        .padding(.horizontal, 20)
                    }
                }
                .padding(.bottom, GRLayout.dockClearance)
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load() }
        .refreshable { await model.load() }
    }

    private func topicSection(_ topic: String, items: [QuizHistoryItem]) -> some View {
        let open = model.openTopic == topic
        return GlassCard(cornerRadius: 16) {
            VStack(alignment: .leading, spacing: 10) {
                Button {
                    model.openTopic = open ? nil : topic
                } label: {
                    HStack {
                        ZStack {
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(GRColor.accent.opacity(0.15))
                                .frame(width: 32, height: 32)
                            Image(systemName: "brain.head.profile")
                                .font(.system(size: 13, weight: .semibold))
                                .foregroundStyle(GRColor.accent)
                        }
                        Text(topic)
                            .font(GRType.headline)
                            .foregroundStyle(GRColor.textPrimary)
                        Spacer()
                        Text("\(items.count) Qs")
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textTertiary)
                        Image(systemName: "chevron.down")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(GRColor.textTertiary)
                            .rotationEffect(.degrees(open ? 180 : 0))
                    }
                }
                .buttonStyle(.plain)

                if open {
                    ForEach(items) { q in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(q.displayQuestion)
                                .font(GRType.body)
                                .foregroundStyle(GRColor.textPrimary)
                            Text("Answer: \(q.displayAnswer)")
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.accent)
                            if let d = q.createdAt {
                                Text(ProfileDateFormat.short(d))
                                    .font(GRType.micro)
                                    .foregroundStyle(GRColor.textTertiary)
                                    .frame(maxWidth: .infinity, alignment: .trailing)
                            }
                        }
                        .padding(10)
                        .background(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .fill(GRColor.fillSubtle)
                        )
                    }
                }
            }
        }
    }
}

// MARK: - Calendar schedule

struct CalendarScheduleView: View {
    let schedule: [ScheduleDay]
    @State private var expandedDate: String?

    private var dayMap: [String: ScheduleDay] {
        Dictionary(uniqueKeysWithValues: schedule.map { ($0.date, $0) })
    }

    var body: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Recall Schedule")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Spacer()
                    Text("Next 14 Days")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textTertiary)
                }

                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(0..<14, id: \.self) { offset in
                            dayCell(offset: offset)
                        }
                    }
                }

                if let expandedDate,
                   let day = dayMap[expandedDate],
                   !day.topics.isEmpty {
                    Divider().overlay(GRColor.stroke)
                    Text("\(friendlyDate(expandedDate)) — \(day.count) topics")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                    FlowTopics(topics: day.topics, totalCount: day.count)
                }
            }
        }
    }

    private func dayCell(offset: Int) -> some View {
        let date = Calendar.current.date(byAdding: .day, value: offset, to: Date()) ?? Date()
        let key = dayKey(date)
        let scheduled = dayMap[key]
        let count = scheduled?.count ?? 0
        let isToday = offset == 0
        let isExpanded = expandedDate == key
        let weekday = DateFormatter()
        weekday.locale = Locale(identifier: "en_US")
        weekday.dateFormat = "EEE"
        let dayNum = Calendar.current.component(.day, from: date)

        return Button {
            guard count > 0 else { return }
            expandedDate = isExpanded ? nil : key
        } label: {
            VStack(spacing: 6) {
                Text(weekday.string(from: date).uppercased())
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                Text("\(dayNum)")
                    .font(GRType.headline)
                    .foregroundStyle(isToday ? GRColor.textPrimary : GRColor.textSecondary)
                if count > 0 {
                    Text("\(count)")
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.accent)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(
                            Capsule()
                                .fill(GRColor.accent.opacity(0.18))
                                .overlay(Capsule().stroke(GRColor.accent.opacity(0.35), lineWidth: 1))
                        )
                } else {
                    Circle()
                        .fill(Color.white.opacity(0.10))
                        .frame(width: 4, height: 4)
                        .padding(.top, 6)
                }
            }
            .frame(width: 52, height: 78)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(isToday || isExpanded ? Color.white.opacity(0.10) : Color.black.opacity(0.20))
                    .overlay(
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .stroke(
                                isExpanded
                                    ? GRColor.accent.opacity(0.55)
                                    : (isToday ? Color.white.opacity(0.20) : Color.white.opacity(0.06)),
                                lineWidth: 1
                            )
                    )
            )
            .opacity(count > 0 || isToday ? 1 : 0.55)
        }
        .buttonStyle(.plain)
        .disabled(count == 0)
        .accessibilityLabel("\(weekday.string(from: date)) \(dayNum), \(count) reviews")
    }

    private func dayKey(_ date: Date) -> String {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(secondsFromGMT: 0)
        f.dateFormat = "yyyy-MM-dd"
        // Align with web ISO date (UTC day) while displaying local weekday/day.
        // Use local calendar day components for the key so "today" matches UI.
        let local = Calendar.current
        let comps = local.dateComponents([.year, .month, .day], from: date)
        var utcCal = Calendar(identifier: .gregorian)
        utcCal.timeZone = TimeZone(secondsFromGMT: 0)!
        if let y = comps.year, let m = comps.month, let d = comps.day,
           let utcDate = utcCal.date(from: DateComponents(year: y, month: m, day: d)) {
            return f.string(from: utcDate)
        }
        return f.string(from: date)
    }

    private func friendlyDate(_ key: String) -> String {
        let inF = DateFormatter()
        inF.locale = Locale(identifier: "en_US_POSIX")
        inF.timeZone = TimeZone(secondsFromGMT: 0)
        inF.dateFormat = "yyyy-MM-dd"
        guard let date = inF.date(from: key) else { return key }
        let out = DateFormatter()
        out.locale = Locale(identifier: "en_US")
        out.dateFormat = "EEEE, MMM d"
        return out.string(from: date)
    }
}

private struct FlowTopics: View {
    let topics: [String]
    let totalCount: Int

    var body: some View {
        FlexibleTopicWrap(topics: topics, extra: max(0, totalCount - topics.count))
    }
}

/// Simple wrapping layout for topic chips without extra deps.
private struct FlexibleTopicWrap: View {
    let topics: [String]
    let extra: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(rows, id: \.self) { row in
                HStack(spacing: 6) {
                    ForEach(row, id: \.self) { topic in
                        Text(topic)
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.accent)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(
                                Capsule()
                                    .fill(GRColor.accent.opacity(0.10))
                                    .overlay(Capsule().stroke(GRColor.accent.opacity(0.22), lineWidth: 1))
                            )
                    }
                }
            }
            if extra > 0 {
                Text("+\(extra) more")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Capsule().fill(GRColor.fillSubtle))
            }
        }
    }

    private var rows: [[String]] {
        // Chunk ~3 chips per row for phone width.
        stride(from: 0, to: topics.count, by: 3).map {
            Array(topics[$0..<min($0 + 3, topics.count)])
        }
    }
}
