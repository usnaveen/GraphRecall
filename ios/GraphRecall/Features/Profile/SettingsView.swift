import SwiftUI
import UserNotifications

/// Grouped settings: account, study habits, imports, data and developer options.
struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @AppStorage("graphrecall.apiBase") private var apiBase: String = APIConfig.baseURL.absoluteString
    @AppStorage(GRSettingsKey.displayName) private var displayName = ""
    @AppStorage(GRSettingsKey.haptics) private var haptics = true
    @AppStorage(GRSettingsKey.reviewImports) private var reviewImports = true
    @AppStorage(GRSettingsKey.remindersEnabled) private var remindersEnabled = false
    @AppStorage(GRSettingsKey.reminderMinutes) private var reminderMinutes = 20 * 60 + 30

    @AppStorage(GRSettingsKey.dailyGoal) private var dailyGoal = 0
    @AppStorage(GRSettingsKey.newCardsPerDay) private var newCardsPerDay = 10

    private let auth = AuthSession.shared
    @State private var studySyncTask: Task<Void, Never>?
    @State private var message: String?
    @State private var confirmPurge = false
    @State private var isPurging = false

    var body: some View {
        NavigationStack {
            ZStack {
                GRColor.canvas.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        accountCard

                        if let message {
                            GRBanner(systemImage: "info.circle.fill", title: message, tone: .accent)
                        }

                        SettingsGroup(title: "Study") {
                            SettingsRow(
                                title: "Daily goal",
                                subtitle: dailyGoal == 0 ? "Auto — matches what’s due" : "Cards to finish each day",
                                systemImage: "target",
                                tone: .accent
                            ) {
                                Picker("Daily goal", selection: $dailyGoal) {
                                    Text("Auto").tag(0)
                                    ForEach([10, 20, 30, 50, 75, 100], id: \.self) { Text("\($0)").tag($0) }
                                }
                                .labelsHidden()
                                .pickerStyle(.menu)
                                .tint(GRColor.accent)
                            }
                            SettingsDivider()
                            SettingsRow(
                                title: "New cards per day",
                                subtitle: "Cap on fresh cards generated for you",
                                systemImage: "sparkles",
                                tone: .cyan
                            ) {
                                Picker("New cards per day", selection: $newCardsPerDay) {
                                    ForEach([0, 5, 10, 15, 20, 30, 50], id: \.self) { Text("\($0)").tag($0) }
                                }
                                .labelsHidden()
                                .pickerStyle(.menu)
                                .tint(GRColor.accent)
                            }
                            SettingsDivider()
                            SettingsRow(title: "Review reminders", subtitle: "A daily nudge when cards are due", systemImage: "bell.fill", tone: .accent) {
                                Toggle("", isOn: $remindersEnabled)
                                    .labelsHidden()
                                    .tint(GRColor.accent)
                            }
                            if remindersEnabled {
                                SettingsDivider()
                                SettingsRow(title: "Reminder time", systemImage: "clock.fill", tone: .cyan) {
                                    DatePicker("", selection: reminderTime, displayedComponents: .hourAndMinute)
                                        .labelsHidden()
                                        .tint(GRColor.accent)
                                }
                            }
                            SettingsDivider()
                            SettingsRow(title: "Haptics", subtitle: "Taps when you grade and navigate", systemImage: "hand.tap.fill", tone: .purple) {
                                Toggle("", isOn: $haptics)
                                    .labelsHidden()
                                    .tint(GRColor.accent)
                            }
                        }

                        SettingsGroup(title: "Graph & imports") {
                            SettingsRow(title: "Review imports before adding", subtitle: "Approve extracted concepts from text, scans and voice", systemImage: "checklist", tone: .amber) {
                                Toggle("", isOn: $reviewImports)
                                    .labelsHidden()
                                    .tint(GRColor.accent)
                            }
                        }

                        SettingsGroup(title: "Data") {
                            Button {
                                Task {
                                    await OfflineReviewStore.shared.clearAll()
                                    message = "Offline review cache cleared"
                                }
                            } label: {
                                SettingsRow(title: "Clear offline review cache", systemImage: "arrow.triangle.2.circlepath", tone: .cyan) {
                                    Image(systemName: "chevron.right")
                                        .font(.system(size: 12, weight: .semibold))
                                        .foregroundStyle(GRColor.textTertiary)
                                }
                            }
                            .buttonStyle(.plain)
                            SettingsDivider()
                            Button {
                                confirmPurge = true
                            } label: {
                                SettingsRow(title: "Delete all my data", subtitle: canUseAccount ? "Notes, concepts, cards and chats" : "Sign in with Google first", systemImage: "trash.fill", tone: .danger, titleColor: GRColor.danger) {
                                    if isPurging { ProgressView().tint(GRColor.danger) }
                                }
                            }
                            .buttonStyle(.plain)
                            .disabled(!canUseAccount || isPurging)
                        }

                        SettingsGroup(title: "Developer") {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("API base URL")
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.textTertiary)
                                TextField("http://127.0.0.1:8000", text: $apiBase)
                                    .textInputAutocapitalization(.never)
                                    .autocorrectionDisabled()
                                    .keyboardType(.URL)
                                    .font(GRType.body)
                                    .foregroundStyle(GRColor.textPrimary)
                                    .padding(12)
                                    .background(GRColor.fillSubtle, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                            }
                            .padding(14)
                        }

                        Text("GraphRecall \(appVersion) · com.usnaveen.graphrecall")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                            .frame(maxWidth: .infinity)
                    }
                    .padding(20)
                    .padding(.bottom, 24)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .foregroundStyle(GRColor.accent)
                }
            }
            .confirmationDialog("Delete all your GraphRecall data?", isPresented: $confirmPurge, titleVisibility: .visible) {
                Button("Delete everything", role: .destructive) {
                    Task { await purge() }
                }
            } message: {
                Text("This permanently removes your notes, concepts, cards and chats from the server. It can’t be undone.")
            }
        }
        .preferredColorScheme(.dark)
        .onChange(of: remindersEnabled) { _, enabled in
            Task { await updateReminders(enabled: enabled) }
        }
        .onChange(of: dailyGoal) { _, _ in scheduleStudySync() }
        .onChange(of: newCardsPerDay) { _, _ in scheduleStudySync() }
    }

    /// Server-backed actions need a real Google session; the demo token is local-only.
    private var canUseAccount: Bool {
        if case .google = auth.state { return true }
        return false
    }

    private var accountCard: some View {
        GlassCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 12) {
                    Text(String((displayName.isEmpty ? "G" : displayName).prefix(1)).uppercased())
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.accent)
                        .frame(width: 44, height: 44)
                        .background(GRColor.accentSoft, in: Circle())
                    VStack(alignment: .leading, spacing: 2) {
                        TextField("Your name", text: $displayName)
                            .font(GRType.headline)
                            .foregroundStyle(GRColor.textPrimary)
                        Text(auth.statusLabel)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textSecondary)
                    }
                    Spacer()
                }

                if let error = auth.lastError {
                    Text(error)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.amber)
                }

                if auth.isSignedIn {
                    Button {
                        Task {
                            await auth.signOut()
                            message = "Signed out"
                        }
                    } label: {
                        Text("Sign out")
                    }
                    .buttonStyle(GRButtonStyle(kind: .secondary, compact: true))
                } else {
                    Button {
                        Task { await auth.signInWithGoogle() }
                    } label: {
                        Label(auth.isWorking ? "Signing in…" : "Continue with Google", systemImage: "person.crop.circle.badge.checkmark")
                    }
                    .buttonStyle(GRButtonStyle(kind: .primary, compact: true))
                    .disabled(auth.isWorking)

                    Button {
                        Task {
                            await auth.useDemoSession()
                            message = "Using the demo session"
                        }
                    } label: {
                        Text("Use demo session")
                    }
                    .buttonStyle(GRButtonStyle(kind: .ghost, compact: true))

                    if !auth.isGoogleConfigured {
                        Text("Google Sign-In needs your client IDs — see ios/Config/Google.local.xcconfig.example.")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                    }
                }
            }
        }
    }

    private func scheduleStudySync() {
        studySyncTask?.cancel()
        studySyncTask = Task {
            try? await Task.sleep(nanoseconds: 700_000_000)
            guard !Task.isCancelled else { return }
            NotificationCenter.default.post(name: .grFeedShouldReload, object: nil)
            guard canUseAccount else {
                message = "Saved on this device — sign in with Google to sync it to your account."
                return
            }
            do {
                try await APIClient.shared.updateStudyPreferences(dailyGoal: dailyGoal, newCardsPerDay: newCardsPerDay)
                message = "Study preferences synced"
            } catch {
                message = "Saved on this device. " + APIError.userFacing(error, resource: "profile")
            }
        }
    }

    private var reminderTime: Binding<Date> {
        Binding(
            get: {
                Calendar.current.date(bySettingHour: reminderMinutes / 60, minute: reminderMinutes % 60, second: 0, of: Date()) ?? Date()
            },
            set: { date in
                let parts = Calendar.current.dateComponents([.hour, .minute], from: date)
                reminderMinutes = (parts.hour ?? 20) * 60 + (parts.minute ?? 30)
                Task { await ReminderScheduler.schedule(minutes: reminderMinutes) }
            }
        )
    }

    private var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—"
    }

    private func updateReminders(enabled: Bool) async {
        if enabled {
            let granted = await ReminderScheduler.requestAndSchedule(minutes: reminderMinutes)
            if !granted {
                remindersEnabled = false
                message = "Allow notifications for GraphRecall in iOS Settings to get reminders."
            } else {
                message = "Daily reminder set"
            }
        } else {
            ReminderScheduler.cancel()
        }
    }

    private func purge() async {
        isPurging = true
        defer { isPurging = false }
        do {
            try await APIClient.shared.purgeMyData()
            await OfflineReviewStore.shared.clearAll()
            RecentImportsStore.shared.clear()
            GRHaptics.warning()
            message = "All data deleted"
        } catch {
            message = APIError.userFacing(error, resource: "account data")
        }
    }
}

enum ReminderScheduler {
    static let identifier = "graphrecall.daily-review"

    static func requestAndSchedule(minutes: Int) async -> Bool {
        let granted = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        guard granted else { return false }
        await schedule(minutes: minutes)
        return true
    }

    static func schedule(minutes: Int) async {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: [identifier])
        let content = UNMutableNotificationContent()
        content.title = "Time for today’s review"
        content.body = "A few minutes keeps your streak — and your memory — alive."
        content.sound = .default
        var components = DateComponents()
        components.hour = minutes / 60
        components.minute = minutes % 60
        let trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: true)
        try? await center.add(UNNotificationRequest(identifier: identifier, content: content, trigger: trigger))
    }

    static func cancel() {
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [identifier])
    }
}

private struct SettingsGroup<Content: View>: View {
    let title: String
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased())
                .font(GRType.micro)
                .tracking(0.6)
                .foregroundStyle(GRColor.textTertiary)
                .padding(.leading, 4)
            VStack(spacing: 0) {
                content()
            }
            .grGlassEffect(in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        }
    }
}

private struct SettingsRow<Trailing: View>: View {
    let title: String
    var subtitle: String? = nil
    let systemImage: String
    var tone: GRTone = .accent
    var titleColor: Color = GRColor.textPrimary
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(spacing: 12) {
            GRIconTile(systemImage: systemImage, tone: tone, size: 30)
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(GRType.body)
                    .foregroundStyle(titleColor)
                if let subtitle {
                    Text(subtitle)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textTertiary)
                }
            }
            Spacer(minLength: 8)
            trailing()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .contentShape(Rectangle())
    }
}

private struct SettingsDivider: View {
    var body: some View {
        Rectangle()
            .fill(GRColor.fillSubtle)
            .frame(height: 1)
            .padding(.leading, 56)
    }
}
