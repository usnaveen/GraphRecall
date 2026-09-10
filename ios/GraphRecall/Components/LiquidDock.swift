import SwiftUI

enum GRTab: String, CaseIterable, Identifiable {
    case feed, graph, create, assistant, profile
    var id: String { rawValue }

    var title: String {
        switch self {
        case .feed: return "Feed"
        case .graph: return "Graph"
        case .create: return "Create"
        case .assistant: return "Assistant"
        case .profile: return "Profile"
        }
    }

    var systemImage: String {
        switch self {
        case .feed: return "house.fill"
        case .graph: return "point.3.connected.trianglepath.dotted"
        case .create: return "plus"
        case .assistant: return "bubble.left.and.bubble.right.fill"
        case .profile: return "person.fill"
        }
    }
}

struct LiquidDock: View {
    @Binding var selection: GRTab
    @Namespace private var glassNS

    var body: some View {
        HStack(spacing: 2) {
            ForEach(GRTab.allCases) { tab in
                dockButton(tab)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background { dockBackground }
        .padding(.horizontal, 20)
        .padding(.bottom, 8)
    }

    @ViewBuilder
    private func dockButton(_ tab: GRTab) -> some View {
        let isCenter = tab == .create
        let isActive = selection == tab

        Button {
            withAnimation(.spring(response: 0.35, dampingFraction: 0.78)) {
                selection = tab
            }
        } label: {
            VStack(spacing: 2) {
                ZStack {
                    if isCenter {
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: [GRColor.accent, GRColor.accentCyan],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                            .frame(width: 46, height: 46)
                            .offset(y: -8)
                            .shadow(color: GRColor.accent.opacity(0.45), radius: 12, y: 4)
                    } else if isActive {
                        if #available(iOS 26.0, *) {
                            Capsule()
                                .fill(GRColor.accent.opacity(0.22))
                                .glassEffectID(tab.rawValue, in: glassNS)
                                .frame(width: 44, height: 36)
                        } else {
                            Capsule()
                                .fill(GRColor.accent.opacity(0.22))
                                .frame(width: 44, height: 36)
                        }
                    }

                    Image(systemName: tab.systemImage)
                        .font(.system(size: isCenter ? 18 : 16, weight: isActive || isCenter ? .semibold : .regular))
                        .foregroundStyle(isCenter ? Color(red: 0.027, green: 0.027, blue: 0.039) : (isActive ? GRColor.accent : GRColor.textSecondary))
                        .offset(y: isCenter ? -8 : 0)
                        .frame(width: 44, height: isCenter ? 44 : 36)
                }

                Text(tab.title)
                    .font(GRType.micro)
                    .foregroundStyle(isActive || isCenter ? GRColor.accent : GRColor.textTertiary)
                    .opacity(1)
            }
            .frame(maxWidth: .infinity)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(tab.title)
    }

    @ViewBuilder
    private var dockBackground: some View {
        let shape = Capsule(style: .continuous)
        if #available(iOS 26.0, *) {
            GlassEffectContainer(spacing: 12) {
                shape
                    .fill(Color.clear)
                    .frame(height: 64)
                    .glassEffect(.regular.interactive(), in: shape)
            }
        } else {
            shape
                .fill(.ultraThinMaterial)
                .overlay(shape.stroke(GRColor.stroke, lineWidth: 1))
                .shadow(color: .black.opacity(0.35), radius: 20, y: 8)
                .frame(height: 64)
        }
    }
}
