import SwiftUI

struct ChatView: View {
    @State private var model = ChatViewModel()
    @FocusState private var inputFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            header
            messagesScroll
            if !model.suggestions.isEmpty && model.messages.count <= 2 {
                suggestionsRow
            }
            composer
        }
        .padding(.bottom, GRLayout.dockClearance)
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
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .grGlassEffect(in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            if !isUser { Spacer(minLength: 24) }
        }
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
