import SwiftUI

/// First-launch welcome — explains the capture → graph → review loop.
struct WelcomeView: View {
    var onFinish: () -> Void
    @State private var appeared = false

    var body: some View {
        ZStack {
            GRColor.canvas.ignoresSafeArea()
            ConstellationBackdrop()
                .frame(height: 480)
                .frame(maxHeight: .infinity, alignment: .top)
                .ignoresSafeArea()
            Circle()
                .fill(GRColor.accent.opacity(0.14))
                .frame(width: 300, height: 300)
                .blur(radius: 90)
                .offset(y: -80)
                .allowsHitTesting(false)

            VStack(spacing: 14) {
                Spacer()

                Image(systemName: "point.3.connected.trianglepath.dotted")
                    .font(.system(size: 36, weight: .bold))
                    .foregroundStyle(GRColor.canvas)
                    .frame(width: 76, height: 76)
                    .background(
                        LinearGradient(colors: [GRColor.accent, GRColor.accentCyan], startPoint: .topLeading, endPoint: .bottomTrailing),
                        in: RoundedRectangle(cornerRadius: 22, style: .continuous)
                    )
                    .shadow(color: GRColor.accent.opacity(0.35), radius: 12, y: 4)

                Text("GraphRecall")
                    .font(GRType.largeTitle)
                    .foregroundStyle(GRColor.textPrimary)
                Text("Turn what you read into a knowledge graph — and actually remember it.")
                    .font(GRType.body)
                    .foregroundStyle(GRColor.textSecondary)
                    .multilineTextAlignment(.center)

                VStack(alignment: .leading, spacing: 12) {
                    feature("square.and.arrow.down.fill", tone: .accent, title: "Dump anything", subtitle: "PDFs, links, YouTube, chats, scans, voice")
                    feature("point.3.connected.trianglepath.dotted", tone: .cyan, title: "See how ideas connect", subtitle: "Concepts link themselves into a graph")
                    feature("bolt.fill", tone: .amber, title: "Remember with spaced repetition", subtitle: "A few minutes a day, cards tuned to you")
                }
                .padding(.vertical, 8)

                Button(action: onFinish) {
                    Label("Get started", systemImage: "arrow.right")
                }
                .buttonStyle(.grPrimary)

                Button {
                    Task {
                        await APIClient.shared.setAccessToken("demo-local-token")
                        onFinish()
                    }
                } label: {
                    Label("Use demo session", systemImage: "play.fill")
                }
                .buttonStyle(.grSecondary)

                Text("You can sign in later from Profile → Settings.")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 16)
            .opacity(appeared ? 1 : 0)
            .offset(y: appeared ? 0 : 24)
        }
        .preferredColorScheme(.dark)
        .onAppear {
            withAnimation(.spring(response: 0.6, dampingFraction: 0.85)) { appeared = true }
        }
    }

    private func feature(_ icon: String, tone: GRTone, title: String, subtitle: String) -> some View {
        HStack(spacing: 12) {
            GRIconTile(systemImage: icon, tone: tone, size: 40)
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(GRType.headline)
                    .foregroundStyle(GRColor.textPrimary)
                Text(subtitle)
                    .font(GRType.caption)
                    .foregroundStyle(GRColor.textSecondary)
            }
            Spacer(minLength: 0)
        }
    }
}

private struct ConstellationBackdrop: View {
    var body: some View {
        Canvas { context, size in
            var seed: UInt64 = 11
            func random() -> Double {
                seed = seed &* 6364136223846793005 &+ 1442695040888963407
                return Double(seed >> 33) / Double(UInt64(1) << 31)
            }
            let points = (0..<26).map { _ in
                CGPoint(x: 20 + random() * (size.width - 40), y: 60 + random() * (size.height - 120))
            }
            for i in points.indices {
                for j in (i + 1)..<points.count {
                    let distance = hypot(points[i].x - points[j].x, points[i].y - points[j].y)
                    guard distance < 110 else { continue }
                    var path = Path()
                    path.move(to: points[i])
                    path.addLine(to: points[j])
                    context.stroke(path, with: .color(.white.opacity(0.14 * (1 - distance / 110) + 0.03)), lineWidth: 1)
                }
            }
            for (i, point) in points.enumerated() {
                let lime = i % 7 == 0, cyan = i % 5 == 0
                let r: CGFloat = lime ? 5 : (cyan ? 4 : 2.5)
                let color: Color = lime ? GRColor.accent : (cyan ? GRColor.accentCyan : .white.opacity(0.35))
                context.fill(Path(ellipseIn: CGRect(x: point.x - r, y: point.y - r, width: r * 2, height: r * 2)), with: .color(color))
            }
        }
        .mask(LinearGradient(colors: [.black, .black, .clear], startPoint: .top, endPoint: .bottom))
        .allowsHitTesting(false)
    }
}

#Preview {
    WelcomeView(onFinish: {})
}
