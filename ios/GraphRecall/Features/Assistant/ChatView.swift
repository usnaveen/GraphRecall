import SwiftUI

struct ChatView: View {
    @State private var model = ChatViewModel()
    @FocusState private var inputFocused: Bool

    private let quizAccent = Color(red: 0.608, green: 0.349, blue: 0.714) // web #9B59B6

    var body: some View {
        ZStack(alignment: .top) {
            GRColor.canvas.ignoresSafeArea()
            VStack(spacing: 0) {
                header
                messagesScroll
                if !model.suggestions.isEmpty && model.messages.count <= 2 {
                    suggestionsRow
                }
                composer
            }
            .padding(.bottom, GRLayout.dockClearance)

            if let banner = model.bannerMessage {
                Text(banner)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textPrimary)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .grGlassEffect(.regular, in: Capsule())
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .zIndex(2)
            }
        }
        .animation(.easeOut(duration: 0.22), value: model.bannerMessage)
        .task { await model.onAppear() }
    }

    private var header: some View {
        HStack(alignment: .top, spacing: 12) {
            GRScreenHeader(
                title: "Assistant",
                subtitle: model.usingStub ? "Offline demo" : "Connected"
            )
            if model.isStreaming {
                Button {
                    model.cancelStream()
                } label: {
                    Image(systemName: "stop.circle.fill")
                        .foregroundStyle(GRColor.accent)
                        .padding(10)
                        .grGlassEffect(.interactive, in: Circle())
                }
                .padding(.trailing, 20)
                .padding(.top, 12)
            }
        }
    }

    private var messagesScroll: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if let error = model.errorMessage {
                        GlassCard(cornerRadius: 14) {
                            Text(error)
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.warning)
                        }
                    }
                    ForEach(model.messages) { message in
                        messageBubble(message)
                            .id(message.id)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 12)
            }
            .onChange(of: model.messages.last?.content) { _, _ in
                if let id = model.messages.last?.id {
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo(id, anchor: .bottom)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func messageBubble(_ message: ChatMessageUI) -> some View {
        let isUser = message.role == .user
        HStack {
            if isUser { Spacer(minLength: 40) }
            VStack(alignment: .leading, spacing: 8) {
                Text(message.content.isEmpty && message.isStreaming ? "…" : message.content)
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textPrimary)
                    .textSelection(.enabled)
                if let status = message.status, message.isStreaming {
                    Text(status)
                        .font(GRType.caption)
                        .foregroundStyle(GRColor.accent)
                }
                if !message.relatedConcepts.isEmpty {
                    FlowChips(items: message.relatedConcepts)
                }
                if !message.sources.isEmpty {
                    Text("Sources: " + message.sources.map(\.title).joined(separator: " · "))
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.textTertiary)
                }
                if showsFeedActions(message) {
                    feedActions(for: message)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .grGlassEffect(in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            if !isUser { Spacer(minLength: 24) }
        }
    }

    private func showsFeedActions(_ message: ChatMessageUI) -> Bool {
        message.role == .assistant
            && !message.isStreaming
            && !message.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && message.status == nil
    }

    @ViewBuilder
    private func feedActions(for message: ChatMessageUI) -> some View {
        let busy = model.actionBusyMessageId == message.id
        VStack(alignment: .leading, spacing: 8) {
            Divider().overlay(GRColor.stroke)

            if model.addToFeedMessageId == message.id {
                HStack(spacing: 8) {
                    Button {
                        Task { await model.createCard(from: message, outputType: .quiz) }
                    } label: {
                        Label("Quiz", systemImage: "questionmark.circle")
                            .font(GRType.caption)
                            .foregroundStyle(quizAccent)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 8)
                            .background(Capsule().fill(quizAccent.opacity(0.15)))
                    }
                    .buttonStyle(.plain)
                    .disabled(busy)

                    Button {
                        Task { await model.createCard(from: message, outputType: .conceptCard) }
                    } label: {
                        Label("Flashcard", systemImage: "rectangle.on.rectangle")
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.accentCyan)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 8)
                            .background(Capsule().fill(GRColor.accentCyan.opacity(0.15)))
                    }
                    .buttonStyle(.plain)
                    .disabled(busy)

                    Button {
                        model.toggleAddToFeed(for: message.id)
                    } label: {
                        Image(systemName: "xmark")
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textTertiary)
                            .padding(8)
                            .background(Circle().fill(GRColor.fillSubtle))
                    }
                    .buttonStyle(.plain)
                    .disabled(busy)
                }
            } else {
                HStack(spacing: 12) {
                    Button {
                        model.toggleAddToFeed(for: message.id)
                    } label: {
                        Label("Create card", systemImage: "plus")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                    }
                    .buttonStyle(.plain)
                    .disabled(busy)

                    Button {
                        Task { await model.saveMessage(message) }
                    } label: {
                        Label(
                            model.savedMessageIds.contains(message.id) ? "Saved" : "Save",
                            systemImage: model.savedMessageIds.contains(message.id)
                                ? "bookmark.fill"
                                : "bookmark"
                        )
                        .font(GRType.micro)
                        .foregroundStyle(
                            model.savedMessageIds.contains(message.id)
                                ? GRColor.accent
                                : GRColor.textTertiary
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(busy || model.savedMessageIds.contains(message.id))

                    if busy {
                        ProgressView()
                            .controlSize(.mini)
                            .tint(GRColor.accent)
                    }
                }
            }
        }
        .padding(.top, 4)
    }

    private var suggestionsRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(model.suggestions, id: \.self) { tip in
                    Button {
                        model.sendSuggestion(tip)
                    } label: {
                        Text(tip)
                            .font(GRType.caption)
                            .foregroundStyle(GRColor.textPrimary)
                            .lineLimit(1)
                            .truncationMode(.tail)
                            .frame(maxWidth: 220, alignment: .leading)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .grGlassEffect(.interactive, in: Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 6)
        }
    }

    private var composer: some View {
        HStack(spacing: 10) {
            TextField("Ask your graph…", text: $model.input, axis: .vertical)
                .lineLimit(1...5)
                .focused($inputFocused)
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
                .grGlassEffect(.interactive, in: RoundedRectangle(cornerRadius: 18, style: .continuous))

            Button {
                Task { await model.send() }
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 32))
                    .foregroundStyle(model.canSend ? GRColor.accent : GRColor.textTertiary)
            }
            .disabled(!model.canSend)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
    }
}

/// Simple horizontal wrapping chip row without a layout dependency.
private struct FlowChips: View {
    let items: [String]
    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(items, id: \.self) { item in
                    Text(item)
                        .font(GRType.micro)
                        .foregroundStyle(GRColor.accent)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(Capsule().fill(GRColor.accent.opacity(0.12)))
                }
            }
        }
    }
}

#Preview {
    ZStack {
        GRColor.canvas.ignoresSafeArea()
        ChatView()
    }
    .preferredColorScheme(.dark)
}
