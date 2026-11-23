import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Share-sheet entry point: persists shared links/text to the App Group inbox and immediately
/// starts a background `URLSession` upload for URLs when an API endpoint + token are available.
final class ShareViewController: UIViewController {
    private let model = ShareModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .clear

        let root = ShareSheetView(
            model: model,
            onSave: { [weak self] in self?.save() },
            onCancel: { [weak self] in self?.cancel() }
        )
        let host = UIHostingController(rootView: root)
        host.view.backgroundColor = .clear
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)

        let items = extensionContext?.inputItems as? [NSExtensionItem] ?? []
        model.suggestTitle(items.compactMap { $0.attributedContentText?.string }.first)
        let providers = items.flatMap { $0.attachments ?? [] }
        Task { await model.load(providers: providers) }
    }

    private func save() {
        model.save()
        extensionContext?.completeRequest(returningItems: nil)
    }

    private func cancel() {
        extensionContext?.cancelRequest(withError: NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError))
    }
}

@MainActor
final class ShareModel: ObservableObject {
    @Published var kind: GRSharedImport.Kind = .text
    @Published var content = ""
    @Published var title = ""
    @Published var isLoading = true

    var canSave: Bool {
        !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func suggestTitle(_ text: String?) {
        guard let text = text?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty, text.count < 120 else { return }
        title = text
    }

    func load(providers: [NSItemProvider]) async {
        defer { isLoading = false }
        for provider in providers where provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            if let raw = await Self.loadString(provider, type: .url),
               let normalized = GRShareURLNormalizer.extractURL(from: raw) {
                kind = .url
                content = normalized
                return
            }
        }
        for provider in providers where provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            guard let raw = await Self.loadString(provider, type: .plainText) else { continue }
            let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { continue }
            // Substack and news apps frequently share either a bare scheme-less URL or "Headline URL".
            if let normalized = GRShareURLNormalizer.extractURL(from: text) {
                kind = .url
                if title.isEmpty, text != normalized {
                    let prefix = text.replacingOccurrences(of: normalized, with: "")
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                    if !prefix.isEmpty && prefix.count < 120 { title = prefix }
                }
                content = normalized
            } else {
                kind = .text
                if title == text { title = "" }
                content = text
            }
            return
        }
    }

    func save() {
        let trimmedTitle = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedContent = content.trimmingCharacters(in: .whitespacesAndNewlines)
        let entry = GRSharedImport(
            kind: kind,
            content: trimmedContent,
            title: trimmedTitle.isEmpty ? nil : trimmedTitle,
            status: .pending
        )
        GRShareInbox.append(entry)

        if kind == .url, startBackgroundUpload(for: entry) {
            GRShareInbox.update(id: entry.id, status: .uploading)
        }
    }

    private func startBackgroundUpload(for item: GRSharedImport) -> Bool {
        let lower = item.content.lowercased()
        let isYouTube = lower.contains("youtube.com") || lower.contains("youtu.be")
        guard !isYouTube else { return false }

        // Only read the shared Keychain access_token here; refresh_token stays app-only so extension
        // uploads never race token rotation (RFC 6819). Any 401 is marked `.pending` in ShareInboxDrainer
        // so the main app refreshes once and drains the item cleanly.
        guard let baseString = GRSharedAuth.apiBaseURL,
              let baseURL = URL(string: baseString),
              let token = GRSharedAuth.bearerToken,
              !token.isEmpty,
              token != "demo-local-token",
              let payloadFile = GRShareUploadConfig.payloadFileURL(for: item.id) else {
            return false
        }

        guard let endpoint = URL(string: "/api/v2/ingest/url", relativeTo: baseURL)?.absoluteURL else {
            return false
        }

        let bodyDict = ["url": item.content]
        guard let bodyData = try? JSONSerialization.data(withJSONObject: bodyDict) else {
            return false
        }
        do {
            try bodyData.write(to: payloadFile, options: .atomic)
        } catch {
            return false
        }

        let config = URLSessionConfiguration.background(withIdentifier: GRShareUploadConfig.backgroundSessionId)
        config.sharedContainerIdentifier = GRShared.appGroup
        config.isDiscretionary = false
        config.sessionSendsLaunchEvents = true

        var req = URLRequest(url: endpoint)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

        let session = URLSession(configuration: config)
        let task = session.uploadTask(with: req, fromFile: payloadFile)
        task.taskDescription = item.id.uuidString
        task.resume()
        session.finishTasksAndInvalidate()
        return true
    }

    private static func loadString(_ provider: NSItemProvider, type: UTType) async -> String? {
        await withCheckedContinuation { continuation in
            provider.loadItem(forTypeIdentifier: type.identifier, options: nil) { item, _ in
                switch item {
                case let url as URL: continuation.resume(returning: url.absoluteString)
                case let string as String: continuation.resume(returning: string)
                case let data as Data: continuation.resume(returning: String(data: data, encoding: .utf8))
                default: continuation.resume(returning: nil)
                }
            }
        }
    }
}

private enum SharePalette {
    static let canvas = Color(red: 7 / 255, green: 7 / 255, blue: 10 / 255)
    static let raised = Color(red: 22 / 255, green: 22 / 255, blue: 26 / 255)
    static let lime = Color(red: 182 / 255, green: 1, blue: 46 / 255)
    static let cyan = Color(red: 46 / 255, green: 1, blue: 230 / 255)
}

struct ShareSheetView: View {
    @ObservedObject var model: ShareModel
    var onSave: () -> Void
    var onCancel: () -> Void

    var body: some View {
        VStack {
            Spacer()
            card
        }
        .background(
            Color.black.opacity(0.4)
                .ignoresSafeArea()
                .onTapGesture(perform: onCancel)
        )
        .preferredColorScheme(.dark)
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Image(systemName: "point.3.connected.trianglepath.dotted")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(SharePalette.canvas)
                    .frame(width: 40, height: 40)
                    .background(
                        LinearGradient(colors: [SharePalette.lime, SharePalette.cyan], startPoint: .topLeading, endPoint: .bottomTrailing),
                        in: RoundedRectangle(cornerRadius: 12, style: .continuous)
                    )
                VStack(alignment: .leading, spacing: 1) {
                    Text("Save to GraphRecall")
                        .font(.system(.headline, design: .rounded))
                        .foregroundStyle(.white)
                    Text("Starts ingesting right away")
                        .font(.system(.caption, design: .rounded))
                        .foregroundStyle(.white.opacity(0.6))
                }
                Spacer()
                Button(action: onCancel) {
                    Image(systemName: "xmark")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(.white.opacity(0.8))
                        .frame(width: 32, height: 32)
                        .background(Circle().fill(Color.white.opacity(0.08)))
                }
                .accessibilityLabel("Cancel")
            }

            preview

            TextField("Title (optional)", text: $model.title)
                .font(.system(.body, design: .rounded))
                .foregroundStyle(.white)
                .padding(12)
                .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 12, style: .continuous))

            Button(action: onSave) {
                Label("Save & ingest", systemImage: "arrow.up.circle.fill")
                    .font(.system(.headline, design: .rounded))
                    .foregroundStyle(SharePalette.canvas)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .background(
                        LinearGradient(colors: [SharePalette.lime, SharePalette.cyan], startPoint: .leading, endPoint: .trailing),
                        in: Capsule()
                    )
            }
            .disabled(!model.canSave)
            .opacity(model.canSave ? 1 : 0.5)
        }
        .padding(20)
        .background(
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .fill(SharePalette.raised)
                .overlay(RoundedRectangle(cornerRadius: 28, style: .continuous).stroke(Color.white.opacity(0.08), lineWidth: 1))
        )
        .padding(12)
    }

    @ViewBuilder
    private var preview: some View {
        HStack(alignment: .top, spacing: 10) {
            if model.isLoading {
                ProgressView()
                    .tint(SharePalette.lime)
                Text("Reading what you shared…")
                    .foregroundStyle(.white.opacity(0.6))
            } else if model.canSave {
                Image(systemName: model.kind == .url ? "globe" : "doc.text.fill")
                    .foregroundStyle(model.kind == .url ? SharePalette.cyan : SharePalette.lime)
                Text(model.content)
                    .foregroundStyle(.white.opacity(0.85))
                    .lineLimit(4)
            } else {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                Text("GraphRecall can save links and text. Nothing usable was shared.")
                    .foregroundStyle(.white.opacity(0.7))
            }
            Spacer(minLength: 0)
        }
        .font(.system(.subheadline, design: .rounded))
        .padding(12)
        .background(Color.white.opacity(0.04), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}
