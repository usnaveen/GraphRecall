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

/// Icon-only floating tab bar. Tab names stay available to VoiceOver and UI tests.
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
        // Side inset matches the bottom inset in ContentView, so the dock's corners echo the
        // display's own rounded corners.
        .padding(.horizontal, 14)
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
                    CreateDrop(isActive: isActive)
                } else if isActive {
                    Capsule()
                        .fill(GRColor.accent.opacity(0.12))
                        .overlay(Capsule().strokeBorder(GRColor.accent.opacity(0.28), lineWidth: 1))
                        .frame(width: 46, height: 34)
                        .matchedGeometryEffect(id: "dock.active", in: glassNS)
                }

                Image(systemName: tab.systemImage)
                    .font(.system(size: isCenter ? 19 : 18, weight: isActive || isCenter ? .semibold : .regular))
                    .foregroundStyle(isCenter ? Color.white : (isActive ? GRColor.accent : GRColor.textSecondary))
                    .shadow(color: isCenter ? .black.opacity(0.35) : .clear, radius: 1, y: 0.5)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 46)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(tab.title)
        .accessibilityAddTraits(isActive ? .isSelected : [])
    }

    @ViewBuilder
    private var dockBackground: some View {
        let shape = Capsule(style: .continuous)
        ZStack {
            // A scrim under the glass: content scrolling past stays readable as texture, not text.
            shape.fill(GRColor.canvas.opacity(0.9))
            if #available(iOS 26.0, *) {
                GlassEffectContainer(spacing: 12) {
                    shape
                        .fill(Color.clear)
                        .glassEffect(.regular.interactive(), in: shape)
                }
            } else {
                shape.fill(.ultraThinMaterial)
            }
            shape.strokeBorder(GRColor.stroke, lineWidth: 1)
        }
        .compositingGroup()
        .shadow(color: .black.opacity(0.45), radius: 18, y: 6)
    }
}

/// The Create button — the same accent-glass droplet every primary action in the app uses.
private struct CreateDrop: View {
    var isActive: Bool

    var body: some View {
        GRAccentGlass(shape: Circle(), strength: isActive ? 0.5 : 0.42)
            .frame(width: 44, height: 44)
    }
}
