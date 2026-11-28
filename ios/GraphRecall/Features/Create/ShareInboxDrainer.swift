import Foundation
import SwiftUI

/// Reconnects Share-extension background uploads and drains pending/failed App Group imports
/// on app launch and foreground activation, showing a quiet auto-dismissing status toast.
@MainActor
@Observable
final class ShareInboxDrainer {
    static let shared = ShareInboxDrainer()

    enum ToastTone: Equatable {
        case accent
        case warning
    }

    var isDraining = false
    var revision = 0
    var toastMessage: String?
    var toastDetail: String?
    var toastTone: ToastTone = .accent

    private var toastDismissTask: Task<Void, Never>?
    private let bgDelegate: BackgroundUploadDelegate
    private var bgSession: URLSession?

    private init() {
        self.bgDelegate = BackgroundUploadDelegate()
    }

    func reconnectBackgroundSession() {
        guard bgSession == nil else { return }
        let config = URLSessionConfiguration.background(withIdentifier: GRShareUploadConfig.backgroundSessionId)
        config.sharedContainerIdentifier = GRShared.appGroup
        config.sessionSendsLaunchEvents = true
        bgSession = URLSession(configuration: config, delegate: bgDelegate, delegateQueue: nil)
    }

    func drainIfNeeded() async {
        reconnectBackgroundSession()
        guard !isDraining else { return }

        let hasStubBase = ProcessInfo.processInfo.environment["GRAPHRECALL_API_BASE"] != nil
        let canDrain = hasStubBase || (AuthSession.shared.state != .signedOut && AuthSession.shared.state != .demo)
        guard canDrain else { return }

        let pending = GRShareInbox.pendingOrFailed()
        guard !pending.isEmpty else { return }

        isDraining = true
        defer { isDraining = false }

        for item in pending {
            await ingest(item: item)
        }
    }

    func retry(item: GRSharedImport) async {
        guard !isDraining else { return }
        isDraining = true
        defer { isDraining = false }
        await ingest(item: item)
    }

    func dismissToast() {
        toastDismissTask?.cancel()
        withAnimation(.easeOut(duration: 0.2)) {
            toastMessage = nil
            toastDetail = nil
        }
    }

    fileprivate func handleBackgroundCompletion(
        itemIdString: String?,
        statusCode: Int?,
        data: Data,
        error: Error?
    ) {
        guard let itemIdString, let itemId = UUID(uuidString: itemIdString) else { return }
        defer {
            GRShareUploadConfig.removePayloadFile(for: itemId)
            revision += 1
        }

        if let error {
            let msg = APIError.userFacing(error, resource: "shared link")
            GRShareInbox.update(id: itemId, status: .failed, error: msg)
            showToast(message: "Shared link waiting in Create", detail: msg, tone: .warning)
            return
        }

        if let code = statusCode, !(200..<300).contains(code) {
            if code == 401 {
                // Extension never holds or rotates refresh_token: mark `.pending` on 401 so the main
                // app refreshes once (avoiding reuse-detection revocation) and re-drains cleanly.
                GRShareInbox.update(id: itemId, status: .pending, error: nil)
                Task { await self.drainIfNeeded() }
                return
            }
            let bodyText = String(data: data, encoding: .utf8) ?? ""
            let msg = APIError.userFacing(APIError.http(code, bodyText), resource: "shared link")
            // 4xx other than auth, timeout and rate limit won't succeed on a retry.
            let permanent = (400..<500).contains(code) && ![401, 408, 429].contains(code)
            GRShareInbox.update(id: itemId, status: .failed, error: msg, permanent: permanent)
            showToast(message: "Couldn’t import link", detail: msg, tone: .warning)
            return
        }

        let response = try? JSONDecoder().decode(IngestResponse.self, from: data)
        markSent(id: itemId, title: GRShareInbox.load().first(where: { $0.id == itemId })?.displayTitle ?? "Shared link", response: response)
    }

    private func ingest(item: GRSharedImport) async {
        GRShareInbox.update(id: item.id, status: .uploading)
        revision += 1

        do {
            switch item.kind {
            case .url:
                let lower = item.content.lowercased()
                if lower.contains("youtube.com") || lower.contains("youtu.be") {
                    let yt = try await APIClient.shared.ingestYouTube(url: item.content, title: item.title)
                    GRShareInbox.update(id: item.id, status: .sent, noteId: yt.noteId)
                    RecentImportsStore.shared.add(RecentImport(
                        title: item.displayTitle,
                        kind: "YouTube",
                        status: yt.status,
                        detail: yt.summary
                    ))
                    showToast(message: yt.wasRead ? "Imported video to GraphRecall" : "Saved YouTube link (no transcript)",
                              detail: yt.title ?? item.displayTitle, tone: .accent)
                } else {
                    let resp = try await APIClient.shared.ingestURL(item.content)
                    markSent(id: item.id, title: item.displayTitle, response: resp)
                }

            case .text:
                let resp = try await APIClient.shared.ingestText(
                    content: item.content,
                    title: item.title ?? item.displayTitle,
                    resourceType: "notes"
                )
                markSent(id: item.id, title: item.displayTitle, response: resp)
            }
        } catch {
            let msg = APIError.userFacing(error, resource: "shared link")
            var permanent = false
            if case let APIError.http(code, _) = error {
                permanent = (400..<500).contains(code) && ![401, 408, 429].contains(code)
            }
            GRShareInbox.update(id: item.id, status: .failed, error: msg, permanent: permanent)
            let headline: String
            if case let APIError.http(code, _) = error, (400..<500).contains(code) {
                headline = "Couldn’t import link"
            } else {
                headline = "Shared import paused"
            }
            showToast(message: headline, detail: msg, tone: .warning)
        }
        revision += 1
    }

    private func markSent(id: UUID, title: String, response: IngestResponse?) {
        let warnings = response?.warnings ?? []
        if let err = response?.error, response?.status == "error" {
            // The server read it and rejected it (validation, e.g. a private address): retrying won't help.
            GRShareInbox.update(id: id, status: .failed, error: err, warnings: warnings, permanent: true)
            showToast(message: "Shared ingest failed", detail: err, tone: .warning)
            return
        }

        GRShareInbox.update(
            id: id,
            status: .sent,
            warnings: warnings,
            noteId: response?.noteId
        )
        GRShareUploadConfig.removePayloadFile(for: id)

        let conceptCount = response?.conceptIds.count ?? 0
        let cardCount = response?.flashcardIds.count ?? 0
        let summaryDetail = warnings.first ?? "\(conceptCount) concepts · \(cardCount) cards"
        RecentImportsStore.shared.add(RecentImport(
            title: title,
            kind: "Share",
            status: response?.status ?? "completed",
            detail: summaryDetail
        ))
        if cardCount > 0 {
            NotificationCenter.default.post(name: .grFeedShouldReload, object: nil)
        }

        if response?.statusReason == "completed_duplicate" {
            let dupDetail = warnings.first(where: { !$0.isEmpty }) ?? "already in your library: this link was imported before"
            showToast(message: "Already in your library", detail: dupDetail, tone: .warning)
        } else if let warning = warnings.first, !warning.isEmpty {
            showToast(message: title, detail: warning, tone: .warning)
        } else {
            showToast(message: "Saved \(title)", detail: "Added to your knowledge graph", tone: .accent)
        }
    }

    private func showToast(message: String, detail: String?, tone: ToastTone) {
        toastDismissTask?.cancel()
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            toastMessage = message
            toastDetail = detail
            toastTone = tone
        }
        toastDismissTask = Task {
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            guard !Task.isCancelled else { return }
            dismissToast()
        }
    }
}

private final class BackgroundUploadDelegate: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var buffers: [Int: Data] = [:]

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        lock.lock()
        var existing = buffers[dataTask.taskIdentifier] ?? Data()
        existing.append(data)
        buffers[dataTask.taskIdentifier] = existing
        lock.unlock()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        lock.lock()
        let collected = buffers.removeValue(forKey: task.taskIdentifier) ?? Data()
        lock.unlock()

        let statusCode = (task.response as? HTTPURLResponse)?.statusCode
        let itemId = task.taskDescription
        Task { @MainActor in
            ShareInboxDrainer.shared.handleBackgroundCompletion(
                itemIdString: itemId,
                statusCode: statusCode,
                data: collected,
                error: error
            )
        }
    }
}
