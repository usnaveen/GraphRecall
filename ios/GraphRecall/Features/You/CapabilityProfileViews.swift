import SwiftUI

// Education, courses (with grades and topics) and projects (with skills). Each course topic and
// project skill becomes evidence in your knowledge map, so a strong grade or a shipped project
// counts even before you're quizzed on it.

private func splitList(_ s: String) -> [String] {
    s.split(whereSeparator: { $0 == "," || $0 == "\n" || $0 == ";" })
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
}

// MARK: - Education + courses

@MainActor
@Observable
final class EducationViewModel {
    var profile = UserProfileInfo.empty
    var courses: [UserCourse] = []
    var isLoading = false
    var errorMessage: String?

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let p = APIClient.shared.capabilityProfile()
            async let c = APIClient.shared.courses()
            profile = (try? await p) ?? .empty
            courses = try await c
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "courses")
        }
    }

    func delete(_ course: UserCourse) async {
        courses.removeAll { $0.id == course.id }
        try? await APIClient.shared.deleteCourse(id: course.id)
    }
}

struct EducationView: View {
    @State private var model = EducationViewModel()
    @State private var editingProfile = false
    @State private var addingCourse = false

    var body: some View {
        List {
            Section {
                GRScreenHeader(title: "Education", subtitle: "Courses and grades count as evidence")
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
                profileCard
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: 4, leading: 20, bottom: 8, trailing: 20))
            }
            Section {
                if let err = model.errorMessage {
                    Text(err).font(GRType.caption).foregroundStyle(GRColor.warning).listRowBackground(Color.clear)
                }
                if model.isLoading && model.courses.isEmpty {
                    ProgressView().tint(GRColor.accent).frame(maxWidth: .infinity).listRowBackground(Color.clear)
                }
                if model.courses.isEmpty && !model.isLoading {
                    Text("Add the courses you've taken. Their topics show up in your knowledge map, weighted by your grade.")
                        .font(GRType.caption).foregroundStyle(GRColor.textSecondary)
                        .listRowBackground(Color.clear)
                }
                ForEach(model.courses) { c in
                    courseRow(c)
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 5, leading: 20, bottom: 5, trailing: 20))
                        .swipeActions {
                            Button(role: .destructive) { Task { await model.delete(c) } } label: { Label("Delete", systemImage: "trash") }
                        }
                }
            } header: {
                HStack {
                    Text("Courses").font(GRType.headline).foregroundStyle(GRColor.textPrimary).textCase(nil)
                    Spacer()
                    Button { addingCourse = true } label: { Label("Add", systemImage: "plus") }
                        .font(GRType.caption.weight(.bold)).tint(GRColor.accent).textCase(nil)
                        .accessibilityIdentifier("education.addCourse")
                }
                .padding(.horizontal, 4)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(GRColor.canvas.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.load() }
        .refreshable { await model.load() }
        .sheet(isPresented: $editingProfile) {
            ProfileEditSheet(profile: model.profile) { model.profile = $0 }
        }
        .sheet(isPresented: $addingCourse) {
            CourseEditSheet { course in model.courses.insert(course, at: 0) }
        }
    }

    private var profileCard: some View {
        Button { editingProfile = true } label: {
            HStack(alignment: .top, spacing: 12) {
                GRIconTile(systemImage: "graduationcap.fill", tone: .purple, size: 44)
                VStack(alignment: .leading, spacing: 3) {
                    Text(model.profile.program ?? model.profile.headline ?? "Add your education")
                        .font(GRType.headline).foregroundStyle(GRColor.textPrimary)
                    let line = [model.profile.institution, model.profile.educationStatus,
                                model.profile.graduationYear.map { "Class of \($0)" }].compactMap { $0 }.joined(separator: " · ")
                    Text(line.isEmpty ? "Status, institution, programme, graduation year, goals" : line)
                        .font(GRType.caption).foregroundStyle(GRColor.textSecondary)
                    if let goals = model.profile.goals, !goals.isEmpty {
                        Text(goals).font(GRType.caption).foregroundStyle(GRColor.textTertiary).lineLimit(2)
                    }
                }
                Spacer()
                Image(systemName: "pencil").foregroundStyle(GRColor.textTertiary)
            }
            .padding(14)
            .grGlassEffect(in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("education.editProfile")
    }

    private func courseRow(_ c: UserCourse) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(c.name).font(GRType.headline).foregroundStyle(GRColor.textPrimary)
                    Text([c.code, c.term, c.institution].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(GRType.caption).foregroundStyle(GRColor.textSecondary)
                }
                Spacer()
                if let g = c.grade, !g.isEmpty {
                    Text(g).font(GRType.headline.monospacedDigit()).foregroundStyle(GRColor.accent)
                        .padding(.horizontal, 10).padding(.vertical, 4)
                        .background(GRColor.accentSoft, in: Capsule())
                }
            }
            if !c.topics.isEmpty {
                GRFlowLayout(spacing: 5) {
                    ForEach(c.topics, id: \.self) { GRChip(title: $0, style: .plain, compact: true) }
                }
            }
        }
        .padding(14)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

struct ProfileEditSheet: View {
    @State var profile: UserProfileInfo
    var onSaved: (UserProfileInfo) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var yearText = ""
    @State private var isSaving = false
    @State private var errorMessage: String?
    private let statuses = ["Undergraduate student", "Postgraduate student", "PhD student", "Working professional",
                            "Between roles", "Self-taught"]

    var body: some View {
        NavigationStack {
            Form {
                Section("You") {
                    TextField("Headline, e.g. ML engineer in training", text: binding(\.headline))
                    Picker("Status", selection: binding(\.educationStatus)) {
                        Text("Not set").tag("")
                        ForEach(statuses, id: \.self) { Text($0).tag($0) }
                    }
                }
                Section("Programme") {
                    TextField("Institution", text: binding(\.institution))
                    TextField("Programme, e.g. MTech Data Science", text: binding(\.program))
                    TextField("Graduation year", text: $yearText).keyboardType(.numberPad)
                }
                Section {
                    TextField("What are you working towards?", text: binding(\.goals), axis: .vertical).lineLimit(2...5)
                } header: { Text("Goals") } footer: { Text("Agents you connect can read this to tailor explanations.") }
                if let errorMessage { Section { Text(errorMessage).foregroundStyle(GRColor.warning) } }
            }
            .scrollContentBackground(.hidden)
            .background(GRColor.canvas.ignoresSafeArea())
            .navigationTitle("Education")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await save() } } label: { if isSaving { ProgressView() } else { Text("Save").bold() } }
                        .disabled(isSaving)
                }
            }
        }
        .preferredColorScheme(.dark)
        .tint(GRColor.accent)
        .onAppear { yearText = profile.graduationYear.map(String.init) ?? "" }
    }

    private func binding(_ kp: WritableKeyPath<UserProfileInfo, String?>) -> Binding<String> {
        Binding(get: { profile[keyPath: kp] ?? "" }, set: { profile[keyPath: kp] = $0.isEmpty ? nil : $0 })
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        profile.graduationYear = Int(yearText.trimmingCharacters(in: .whitespaces))
        do {
            let saved = try await APIClient.shared.saveCapabilityProfile(profile)
            GRHaptics.success()
            onSaved(saved)
            dismiss()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "profile")
        }
    }
}

struct CourseEditSheet: View {
    var onSaved: (UserCourse) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var code = ""
    @State private var term = ""
    @State private var grade = ""
    @State private var institution = ""
    @State private var topics = ""
    @State private var isSaving = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Course") {
                    TextField("Name, e.g. Deep Learning", text: $name).accessibilityIdentifier("course.name")
                    TextField("Code, e.g. DA6401", text: $code)
                    TextField("Term, e.g. Jan–May 2026", text: $term)
                    TextField("Institution", text: $institution)
                }
                Section {
                    TextField("Grade: S, A, B+, 8.5, 92%…", text: $grade).textInputAutocapitalization(.characters)
                } header: { Text("Grade") } footer: { Text("Higher grades count as stronger evidence for the course's topics.") }
                Section {
                    TextField("Topics, comma-separated", text: $topics, axis: .vertical).lineLimit(2...6)
                        .accessibilityIdentifier("course.topics")
                } header: { Text("Topics covered") } footer: {
                    Text("e.g. backpropagation, CNNs, transformers. Empty: the course name is used.")
                }
                if let errorMessage { Section { Text(errorMessage).foregroundStyle(GRColor.warning) } }
            }
            .scrollContentBackground(.hidden)
            .background(GRColor.canvas.ignoresSafeArea())
            .navigationTitle("Add course")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await save() } } label: { if isSaving { ProgressView() } else { Text("Save").bold() } }
                        .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || isSaving)
                        .accessibilityIdentifier("course.save")
                }
            }
        }
        .preferredColorScheme(.dark)
        .tint(GRColor.accent)
    }

    private func blank(_ s: String) -> String? {
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        do {
            let c = try await APIClient.shared.addCourse(CourseBody(
                name: name.trimmingCharacters(in: .whitespacesAndNewlines), code: blank(code), term: blank(term),
                grade: blank(grade), institution: blank(institution), topics: splitList(topics)))
            GRHaptics.success()
            onSaved(c)
            dismiss()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "course")
        }
    }
}

// MARK: - Projects

@MainActor
@Observable
final class ProjectsViewModel {
    var projects: [UserProject] = []
    var isLoading = false
    var errorMessage: String?

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            projects = try await APIClient.shared.projects()
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "projects")
        }
    }

    func delete(_ p: UserProject) async {
        projects.removeAll { $0.id == p.id }
        try? await APIClient.shared.deleteProject(id: p.id)
    }
}

struct ProjectsView: View {
    @State private var model = ProjectsViewModel()
    @State private var adding = false
    @Environment(\.openURL) private var openURL

    var body: some View {
        List {
            Section {
                GRScreenHeader(title: "Projects", subtitle: "What you've built is evidence too")
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            }
            if let err = model.errorMessage {
                Text(err).font(GRType.caption).foregroundStyle(GRColor.warning).listRowBackground(Color.clear)
            }
            if model.isLoading && model.projects.isEmpty {
                ProgressView().tint(GRColor.accent).frame(maxWidth: .infinity).listRowBackground(Color.clear)
            }
            if model.projects.isEmpty && !model.isLoading {
                Text("Add projects with the skills they used. Each skill becomes evidence in your knowledge map.")
                    .font(GRType.caption).foregroundStyle(GRColor.textSecondary)
                    .listRowBackground(Color.clear)
            }
            ForEach(model.projects) { p in
                row(p)
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: 5, leading: 20, bottom: 5, trailing: 20))
                    .swipeActions {
                        Button(role: .destructive) { Task { await model.delete(p) } } label: { Label("Delete", systemImage: "trash") }
                    }
                    .contextMenu {
                        if let url = p.url.flatMap(URL.init(string:)) { Button("Open link") { openURL(url) } }
                    }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(GRColor.canvas.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { adding = true } label: { Image(systemName: "plus") }
                    .accessibilityLabel("Add project")
            }
        }
        .task { await model.load() }
        .refreshable { await model.load() }
        .sheet(isPresented: $adding) {
            ProjectEditSheet { p in model.projects.insert(p, at: 0) }
        }
    }

    private func row(_ p: UserProject) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(p.name).font(GRType.headline).foregroundStyle(GRColor.textPrimary)
                Spacer()
                let dates = [p.started, p.ended].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " – ")
                if !dates.isEmpty { Text(dates).font(GRType.micro).foregroundStyle(GRColor.textTertiary) }
            }
            if let s = p.summary, !s.isEmpty {
                Text(s).font(GRType.caption).foregroundStyle(GRColor.textSecondary).lineLimit(3)
            }
            if !p.skills.isEmpty {
                GRFlowLayout(spacing: 5) {
                    ForEach(p.skills, id: \.self) { GRChip(title: $0, style: .tinted(.cyan), compact: true) }
                }
            }
        }
        .padding(14)
        .grGlassEffect(in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

struct ProjectEditSheet: View {
    var onSaved: (UserProject) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var summary = ""
    @State private var url = ""
    @State private var skills = ""
    @State private var started = ""
    @State private var ended = ""
    @State private var isSaving = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Project") {
                    TextField("Name", text: $name).accessibilityIdentifier("project.name")
                    TextField("What it does and your part in it", text: $summary, axis: .vertical).lineLimit(2...6)
                    TextField("Link (optional)", text: $url)
                        .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                }
                Section {
                    TextField("Skills, comma-separated", text: $skills, axis: .vertical).lineLimit(2...5)
                        .accessibilityIdentifier("project.skills")
                } header: { Text("Skills used") } footer: { Text("e.g. LangGraph, pgvector, SwiftUI, knowledge graphs") }
                Section("When") {
                    TextField("Started, e.g. Sep 2026", text: $started)
                    TextField("Ended (blank if ongoing)", text: $ended)
                }
                if let errorMessage { Section { Text(errorMessage).foregroundStyle(GRColor.warning) } }
            }
            .scrollContentBackground(.hidden)
            .background(GRColor.canvas.ignoresSafeArea())
            .navigationTitle("Add project")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await save() } } label: { if isSaving { ProgressView() } else { Text("Save").bold() } }
                        .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || isSaving)
                        .accessibilityIdentifier("project.save")
                }
            }
        }
        .preferredColorScheme(.dark)
        .tint(GRColor.accent)
    }

    private func blank(_ s: String) -> String? {
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        do {
            let p = try await APIClient.shared.addProject(ProjectBody(
                name: name.trimmingCharacters(in: .whitespacesAndNewlines), summary: blank(summary), url: blank(url),
                skills: splitList(skills), started: blank(started), ended: blank(ended)))
            GRHaptics.success()
            onSaved(p)
            dismiss()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "project")
        }
    }
}
