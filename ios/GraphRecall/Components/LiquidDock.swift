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
        HStack(spacing: 4) {
            ForEach(GRTab.allCases) { tab in
                dockButton(tab)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background { dockBackground }
        .padding(.horizontal, 24)
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
                        .frame(width: 48, height: 48)
                        .offset(y: -10)
                        .shadow(color: GRColor.accent.opacity(0.45), radius: 12, y: 4)
                } else if isActive {
                    if #available(iOS 26.0, *) {
                        Capsule()
                            .fill(GRColor.accent.opacity(0.22))
                            .glassEffectID(tab.rawValue, in: glassNS)
                            .frame(width: 44, height: 44)
                    } else {
                        Capsule()
                            .fill(GRColor.accent.opacity(0.22))
                            .frame(width: 44, height: 44)
                    }
                }

                Image(systemName: tab.systemImage)
                    .font(.system(size: isCenter ? 18 : 17, weight: isActive || isCenter ? .semibold : .regular))
                    .foregroundStyle(isCenter ? Color(red: 0.027, green: 0.027, blue: 0.039) : (isActive ? GRColor.accent : GRColor.textSecondary))
                    .offset(y: isCenter ? -10 : 0)
                    .frame(width: 44, height: 44)
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
                    .frame(height: 60)
                    .glassEffect(.regular.interactive(), in: shape)
            }
        } else {
            shape
                .fill(.ultraThinMaterial)
                .overlay(shape.stroke(GRColor.stroke, lineWidth: 1))
                .shadow(color: .black.opacity(0.35), radius: 20, y: 8)
                .frame(height: 60)
        }
    }
}
