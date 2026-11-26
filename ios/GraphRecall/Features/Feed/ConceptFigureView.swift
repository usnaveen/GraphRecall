import SwiftUI
import UIKit

/// A figure cropped from one of the user's own books or papers, chosen by the backend because its
/// caption is about the card's concept (`content["figure"]`, see backend/services/concept_figures.py).
struct ConceptFigure: Equatable, Sendable {
    let id: String
    let path: String
    let label: String
    let caption: String
    let sourceTitle: String
    let page: Int
    let width: Int
    let height: Int

    /// Shape of the full-width panel the figure sits on: its own width over height, clamped so a
    /// tall architecture diagram stays about 170pt high (the grading slider must stay on screen in
    /// the reel; tap for the full figure) and a thin strip still gets room.
    var panelAspectRatio: CGFloat {
        guard width > 0, height > 0 else { return 2.0 }
        return min(max(CGFloat(width) / CGFloat(height), 2.0), 3.2)
    }

    var attribution: String {
        let source = sourceTitle.isEmpty ? "your library" : sourceTitle
        return label.isEmpty ? source : "\(label) · \(source)"
    }
}

extension FeedItem {
    var conceptFigure: ConceptFigure? {
        guard let raw = content["figure"]?.value as? [String: Any],
              let id = raw["id"] as? String, !id.isEmpty,
              let path = raw["url"] as? String, path.hasPrefix("/api/figures/") else { return nil }
        func int(_ key: String) -> Int {
            if let v = raw[key] as? Int { return v }
            if let v = raw[key] as? Double { return Int(v) }
            return 0
        }
        return ConceptFigure(
            id: id,
            path: path,
            label: raw["label"] as? String ?? "",
            caption: raw["caption"] as? String ?? "",
            sourceTitle: raw["source_title"] as? String ?? "",
            page: int("page"),
            width: int("width"),
            height: int("height")
        )
    }
}

/// Decoded figures, kept for the session so scrolling back through the feed never refetches.
@MainActor
final class ConceptFigureCache {
    static let shared = ConceptFigureCache()
    private let images = NSCache<NSString, UIImage>()
    private var inFlight: [String: Task<UIImage?, Never>] = [:]

    private init() {
        images.countLimit = 60
    }

    func image(for figure: ConceptFigure) async -> UIImage? {
        if let cached = images.object(forKey: figure.id as NSString) { return cached }
        if let task = inFlight[figure.id] { return await task.value }
        let path = figure.path
        let task = Task<UIImage?, Never> {
            guard let data = try? await APIClient.shared.getData(path) else { return nil }
            return UIImage(data: data)
        }
        inFlight[figure.id] = task
        let image = await task.value
        inFlight[figure.id] = nil
        if let image { images.setObject(image, forKey: figure.id as NSString) }
        return image
    }
}

/// The figure inline on a card: printed-page figures sit on white, as they were drawn to be read,
/// with where they come from underneath. Tap to see it full screen. If it cannot load, the card
/// simply has no figure.
struct ConceptFigureView: View {
    let figure: ConceptFigure

    @State private var image: UIImage?
    @State private var failed = false
    @State private var showsViewer = false

    var body: some View {
        if failed {
            EmptyView()
        } else {
            VStack(alignment: .leading, spacing: 6) {
                Button {
                    guard image != nil else { return }
                    GRHaptics.tap()
                    showsViewer = true
                } label: {
                    figureFrame
                }
                .buttonStyle(.plain)
                .accessibilityLabel("\(figure.attribution). \(figure.caption)")
                .accessibilityHint("Opens the figure full screen")
                .accessibilityIdentifier("feed.conceptFigure")

                Text(figure.attribution)
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            .task(id: figure.id) {
                image = nil
                let loaded = await ConceptFigureCache.shared.image(for: figure)
                if let loaded {
                    withAnimation(.easeOut(duration: 0.2)) { image = loaded }
                } else {
                    failed = true
                }
            }
            .fullScreenCover(isPresented: $showsViewer) {
                if let image {
                    ConceptFigureViewer(figure: figure, image: image)
                }
            }
        }
    }

    private var figureFrame: some View {
        Color.white
            .aspectRatio(figure.panelAspectRatio, contentMode: .fit)
            .frame(maxWidth: .infinity)
            .overlay {
                if let image {
                    Image(uiImage: image)
                        .resizable()
                        .interpolation(.high)
                        .scaledToFit()
                        .padding(10)
                        .transition(.opacity)
                } else {
                    ProgressView()
                        .controlSize(.small)
                        .tint(.gray)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(GRColor.stroke, lineWidth: 1))
    }
}

/// Full screen: pinch or double-tap to zoom, with the full caption.
private struct ConceptFigureViewer: View {
    let figure: ConceptFigure
    let image: UIImage

    @Environment(\.dismiss) private var dismiss
    @State private var scale: CGFloat = 1
    @State private var settledScale: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var settledOffset: CGSize = .zero

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                Image(uiImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
                    .padding(10)
                    .background(Color.white, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .scaleEffect(scale)
                    .offset(offset)
                    .gesture(
                        MagnifyGesture()
                            .onChanged { scale = min(max(settledScale * $0.magnification, 1), 5) }
                            .onEnded { _ in
                                settledScale = scale
                                if scale == 1 { resetPan() }
                            }
                            .simultaneously(with: DragGesture()
                                .onChanged { value in
                                    guard scale > 1 else { return }
                                    offset = CGSize(
                                        width: settledOffset.width + value.translation.width,
                                        height: settledOffset.height + value.translation.height
                                    )
                                }
                                .onEnded { _ in settledOffset = offset })
                    )
                    .onTapGesture(count: 2) {
                        withAnimation(.snappy) {
                            if scale > 1 {
                                scale = 1
                                settledScale = 1
                                resetPan()
                            } else {
                                scale = 2.5
                                settledScale = 2.5
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .clipped()

                VStack(alignment: .leading, spacing: 6) {
                    Text(figure.caption)
                        .font(.subheadline)
                        .foregroundStyle(GRColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(figure.page > 0 ? "\(figure.attribution), page \(figure.page)" : figure.attribution)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.textTertiary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(16)
            .background(GRColor.canvas.ignoresSafeArea())
            .navigationTitle(figure.label.isEmpty ? "Figure" : figure.label)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .accessibilityIdentifier("feed.conceptFigure.done")
                }
            }
        }
    }

    private func resetPan() {
        offset = .zero
        settledOffset = .zero
    }
}
