import SwiftUI

// "Show me this later": capture now (typed, dictated or a link), get it back in the feed when due.

// MARK: - Capture sheet

struct LaterCaptureSheet: View {
    var initialText: String = ""
    var onSaved: ((LaterItem) -> Void)? = nil

    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var link = ""
    /// No chip by default: a time in your own words ("…on Friday") should win; else tomorrow 9 am.
    @State private var when: LaterWhen?
    @State private var usedVoice = false
    @State private var dictation = GRDictation()
    @State private var isSaving = false
    @State private var errorMessage: String?
    @FocusState private var focused: Bool

    private var canSave: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !link.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Say or type what should come back, and when. “Show me the attention paper on Friday” works too.")
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textSecondary)

                    GlassCard(cornerRadius: 18) {
                        VStack(alignment: .leading, spacing: 10) {
                            HStack(alignment: .top, spacing: 10) {
                                TextField("What should come back?", text: $text, axis: .vertical)
                                    .lineLimit(2...6)
                                    .font(GRType.body)
                                    .foregroundStyle(GRColor.textPrimary)
                                    .focused($focused)
                                    .accessibilityIdentifier("later.text")
                                GRIconButton(
                                    systemImage: dictation.isRecording ? "stop.fill" : "mic.fill",
                                    style: dictation.isRecording ? .accent : .glass,
                                    tint: dictation.isRecording ? GRColor.canvas : GRColor.accent,
                                    size: 40,
                                    accessibilityLabel: dictation.isRecording ? "Stop dictation" : "Dictate"
                                ) { toggleDictation() }
                            }
                            if dictation.isRecording {
                                Label("Listening… say when, too", systemImage: "waveform")
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.accent)
                            }
                            if let err = dictation.errorMessage {
                                Text(err).font(GRType.caption).foregroundStyle(GRColor.warning)
                            }
                            Divider().overlay(GRColor.stroke)
                            TextField("Link (optional)", text: $link)
                                .font(GRType.caption)
                                .keyboardType(.URL)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .foregroundStyle(GRColor.textPrimary)
                        }
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        GRSectionHeader(title: "When")
                        GRFlowLayout(spacing: 8) {
                            ForEach(LaterWhen.allCases) { option in
                                GRChip(title: option.title, style: when == option ? .selected : .plain, compact: true) {
                                    when = when == option ? nil : option
                                    GRHaptics.tap()
                                }
                            }
                        }
                        Text(when == nil ? "No pick: a time in your words is used, else tomorrow 9 am."
                                         : "A time in your words is ignored while a chip is picked.")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                    }

                    if let errorMessage {
                        Text(errorMessage).font(GRType.caption).foregroundStyle(GRColor.warning)
                    }

                    Button {
                        Task { await save() }
                    } label: {
                        if isSaving { ProgressView().tint(GRColor.canvas) } else { Label("Remind me", systemImage: "clock.arrow.circlepath") }
                    }
                    .grButton(.primary)
                    .disabled(!canSave || isSaving)
                    .accessibilityIdentifier("later.save")
                }
                .padding(20)
            }
            .background(GRColor.canvas.ignoresSafeArea())
            .navigationTitle("Remind me")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dictation.stop(); dismiss() }
                }
            }
        }
        .preferredColorScheme(.dark)
        .onAppear {
            if text.isEmpty { text = initialText }
            focused = initialText.isEmpty
        }
        .onDisappear { dictation.stop() }
    }

    private func toggleDictation() {
        GRHaptics.tap()
        if dictation.isRecording {
            dictation.stop()
            return
        }
        usedVoice = true
        Task { await dictation.start { text = $0 } }
    }

    private func save() async {
        dictation.stop()
        isSaving = true
        defer { isSaving = false }
        let trimmedLink = link.trimmingCharacters(in: .whitespacesAndNewlines)
        do {
            let item = try await APIClient.shared.saveForLater(
                text: text.trimmingCharacters(in: .whitespacesAndNewlines),
                url: trimmedLink.isEmpty ? nil : trimmedLink,
                when: when,
                source: usedVoice ? "voice" : "typed"
            )
            GRHaptics.success()
            onSaved?(item)
            dismiss()
        } catch {
            errorMessage = APIError.userFacing(error, resource: "later item")
        }
    }
}

// MARK: - Formatting

enum LaterFormat {
    static func when(_ date: Date?) -> String {
        guard let date else { return "" }
        let cal = Calendar.current
        let time = date.formatted(date: .omitted, time: .shortened)
        if date <= Date() { return "Now" }
        if cal.isDateInToday(date) { return "Today \(time)" }
        if cal.isDateInTomorrow(date) { return "Tomorrow \(time)" }
        if let days = cal.dateComponents([.day], from: cal.startOfDay(for: Date()), to: cal.startOfDay(for: date)).day, days < 7 {
            return "\(date.formatted(.dateTime.weekday(.wide))) \(time)"
        }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

// MARK: - Feed card for due items

/// Sits under the feed's top bar when something you saved is due. Content, not a counter:
/// one item at a time, with the actions inline.
struct LaterDueCard: View {
    @Binding var items: [LaterItem]
    @Environment(\.openURL) private var openURL

    var body: some View {
        if let item = items.first {
            GlassCard(cornerRadius: 18) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 6) {
                        Image(systemName: "clock.arrow.circlepath")
                        Text(items.count > 1 ? "Back as promised · 1 of \(items.count)" : "Back as promised")
                        Spacer()
                        if let phrase = item.whenPhrase, !phrase.isEmpty {
                            Text("“\(phrase)”").foregroundStyle(GRColor.textTertiary)
                        }
                    }
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.accent)

                    Text(item.text)
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                        .lineLimit(4)

                    HStack(spacing: 8) {
                        if let link = item.link {
                            Button { openURL(link) } label: { Label("Open", systemImage: "safari") }
                                .grButton(.ghost, fullWidth: false, compact: true)
                        }
                        Menu {
                            ForEach(LaterWhen.allCases) { option in
                                Button(option.title) { Task { await snooze(item, option) } }
                            }
                        } label: {
                            Label("Snooze", systemImage: "moon.zzz")
                        }
                        .grButton(.secondary, fullWidth: false, compact: true)
                        Spacer()
                        Button { Task { await done(item) } } label: { Label("Done", systemImage: "checkmark") }
                            .grButton(.primary, fullWidth: false, compact: true)
                            .accessibilityIdentifier("later.done")
                    }
                }
            }
            .transition(.move(edge: .top).combined(with: .opacity))
        }
    }

    private func done(_ item: LaterItem) async {
        GRHaptics.success()
        withAnimation(.easeOut(duration: 0.2)) { items.removeAll { $0.id == item.id } }
        try? await APIClient.shared.markLaterDone(id: item.id)
    }

    private func snooze(_ item: LaterItem, _ when: LaterWhen) async {
        GRHaptics.tap()
        withAnimation(.easeOut(duration: 0.2)) { items.removeAll { $0.id == item.id } }
        _ = try? await APIClient.shared.snoozeLater(id: item.id, when: when)
    }
}

// MARK: - Profile list

@MainActor
@Observable
final class LaterListViewModel {
    var items: [LaterItem] = []
    var isLoading = false
    var errorMessage: String?

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            items = try await APIClient.shared.laterItems()
            errorMessage = nil
        } catch {
            errorMessage = APIError.userFacing(error, resource: "saved-for-later items")
        }
    }

    func done(_ item: LaterItem) async {
        items.removeAll { $0.id == item.id }
        try? await APIClient.shared.markLaterDone(id: item.id)
    }

    func snooze(_ item: LaterItem, _ when: LaterWhen) async {
        if let updated = try? await APIClient.shared.snoozeLater(id: item.id, when: when),
           let i = items.firstIndex(where: { $0.id == item.id }) {
            items[i] = updated
            items.sort { ($0.showAt ?? .distantFuture) < ($1.showAt ?? .distantFuture) }
        }
    }
}

struct LaterListView: View {
    @State private var model = LaterListViewModel()
    @State private var showCapture = false
    @Environment(\.openURL) private var openURL

    var body: some View {
        List {
            Section {
                GRScreenHeader(title: "Reminders", subtitle: "\(model.items.count) waiting")
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            }
            if model.isLoading && model.items.isEmpty {
                ProgressView().tint(GRColor.accent).frame(maxWidth: .infinity)
                    .listRowBackground(Color.clear)
            } else if let err = model.errorMessage, model.items.isEmpty {
                Text(err).font(GRType.caption).foregroundStyle(GRColor.warning)
                    .listRowBackground(Color.clear)
            } else if model.items.isEmpty {
                Text("Nothing saved. Tap + and say something like “show me union-find this weekend”.")
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textSecondary)
                    .listRowBackground(Color.clear)
            } else {
                ForEach(model.items) { item in
                    row(item)
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 5, leading: 20, bottom: 5, trailing: 20))
                        .swipeActions(edge: .trailing) {
                            Button { Task { await model.done(item) } } label: { Label("Done", systemImage: "checkmark") }
                                .tint(GRColor.success)
                        }
                        .swipeActions(edge: .leading) {
                            Button { Task { await model.snooze(item, .tomorrow) } } label: { Label("Tomorrow", systemImage: "moon.zzz") }
                                .tint(GRColor.purple)
                        }
                        .contextMenu {
                            if let link = item.link { Button("Open link") { openURL(link) } }
                            ForEach(LaterWhen.allCases) { w in
                                Button("Snooze: \(w.title)") { Task { await model.snooze(item, w) } }
                            }
                            Button("Done") { Task { await model.done(item) } }
                        }
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(GRColor.canvas.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { showCapture = true } label: { Image(systemName: "plus") }
                    .accessibilityLabel("Save something for later")
            }
        }
        .sheet(isPresented: $showCapture) {
            LaterCaptureSheet { _ in Task { await model.load() } }
                .presentationDetents([.medium, .large])
        }
        .task { await model.load() }
        .refreshable { await model.load() }
    }

    private func row(_ item: LaterItem) -> some View {
        GRListRow(
            title: item.text,
            subtitle: item.url,
            meta: LaterFormat.when(item.showAt),
            metaColor: item.isDue ? GRColor.accent : GRColor.textTertiary,
            systemImage: item.source == "voice" ? "mic.fill" : item.url != nil ? "link" : "clock",
            tone: item.isDue ? .accent : .purple,
            showsChevron: false
        )
    }
}
