import SwiftUI
import WidgetKit

@main
struct GraphRecallWidgetBundle: WidgetBundle {
    var body: some Widget {
        DueCardsWidget()
    }
}

struct DueCardsEntry: TimelineEntry {
    let date: Date
    let snapshot: GRReviewSnapshot
}

struct DueCardsProvider: TimelineProvider {
    func placeholder(in context: Context) -> DueCardsEntry {
        DueCardsEntry(date: .now, snapshot: .placeholder)
    }

    func getSnapshot(in context: Context, completion: @escaping (DueCardsEntry) -> Void) {
        completion(DueCardsEntry(date: .now, snapshot: GRReviewSnapshot.load() ?? .placeholder))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<DueCardsEntry>) -> Void) {
        let entry = DueCardsEntry(date: .now, snapshot: GRReviewSnapshot.load() ?? .empty)
        // The app reloads timelines after every load and grade; this is only a safety refresh.
        completion(Timeline(entries: [entry], policy: .after(.now.addingTimeInterval(30 * 60))))
    }
}

struct DueCardsWidget: Widget {
    let kind = "DueCardsWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: DueCardsProvider()) { entry in
            DueCardsWidgetView(entry: entry)
                .containerBackground(for: .widget) { WidgetBackground() }
        }
        .configurationDisplayName("Cards due")
        .description("See what’s due today and jump straight into a review.")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

private enum WidgetPalette {
    static let canvas = Color(red: 7 / 255, green: 7 / 255, blue: 10 / 255)
    static let lime = Color(red: 182 / 255, green: 1, blue: 46 / 255)
    static let cyan = Color(red: 46 / 255, green: 1, blue: 230 / 255)
    static let amber = Color(red: 245 / 255, green: 158 / 255, blue: 11 / 255)
    static let secondary = Color.white.opacity(0.62)
    static let tertiary = Color.white.opacity(0.4)
}

private struct WidgetBackground: View {
    var body: some View {
        ZStack {
            WidgetPalette.canvas
            RadialGradient(
                colors: [WidgetPalette.lime.opacity(0.2), .clear],
                center: .topTrailing,
                startRadius: 0,
                endRadius: 170
            )
        }
    }
}

struct DueCardsWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: DueCardsEntry

    private var snapshot: GRReviewSnapshot { entry.snapshot }

    var body: some View {
        Group {
            switch family {
            case .accessoryCircular: circular
            case .accessoryRectangular: rectangular
            case .accessoryInline: Text(dueLine)
            case .systemMedium: medium
            default: small
            }
        }
        .widgetURL(URL(string: "\(GRShared.urlScheme)://review"))
    }

    private var dueLine: String {
        snapshot.dueCount == 0 ? "All caught up" : "\(snapshot.dueCount) card\(snapshot.dueCount == 1 ? "" : "s") due"
    }

    private var footer: String {
        guard snapshot.hasSynced else { return "Open to sync" }
        return "\(snapshot.completedToday)/\(snapshot.dailyGoal) done today"
    }

    private var header: some View {
        HStack(spacing: 5) {
            Image(systemName: "point.3.connected.trianglepath.dotted")
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(WidgetPalette.lime)
            Text("Today")
                .font(.system(size: 13, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
            Spacer(minLength: 0)
            if snapshot.streak > 0 {
                HStack(spacing: 2) {
                    Image(systemName: "flame.fill")
                    Text("\(snapshot.streak)")
                }
                .font(.system(size: 11, weight: .bold, design: .rounded))
                .foregroundStyle(WidgetPalette.amber)
            }
        }
    }

    private func ring(size: CGFloat) -> some View {
        ZStack {
            Circle()
                .stroke(Color.white.opacity(0.1), lineWidth: 7)
            Circle()
                .trim(from: 0, to: snapshot.goalProgress)
                .stroke(
                    AngularGradient(colors: [WidgetPalette.lime, WidgetPalette.cyan, WidgetPalette.lime], center: .center),
                    style: StrokeStyle(lineWidth: 7, lineCap: .round)
                )
                .rotationEffect(.degrees(-90))
            VStack(spacing: 0) {
                Text("\(snapshot.dueCount)")
                    .font(.system(size: size * 0.36, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)
                    .minimumScaleFactor(0.6)
                Text("due")
                    .font(.system(size: 10, weight: .semibold, design: .rounded))
                    .foregroundStyle(WidgetPalette.secondary)
            }
        }
        .frame(width: size, height: size)
    }

    private var small: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            ring(size: 66)
                .frame(maxWidth: .infinity)
            Text(footer)
                .font(.system(size: 11, weight: .semibold, design: .rounded))
                .foregroundStyle(WidgetPalette.secondary)
                .lineLimit(1)
                .frame(maxWidth: .infinity)
        }
    }

    private var medium: some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 8) {
                header
                ring(size: 72)
                    .frame(maxWidth: .infinity)
                Text(footer)
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(WidgetPalette.secondary)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity)
            }
            .frame(width: 120)

            VStack(alignment: .leading, spacing: 7) {
                Text("UP NEXT")
                    .font(.system(size: 10, weight: .bold, design: .rounded))
                    .tracking(0.6)
                    .foregroundStyle(WidgetPalette.tertiary)
                if snapshot.upNext.isEmpty {
                    Text(snapshot.hasSynced ? "Nothing due — nice work." : "Open GraphRecall to load your queue.")
                        .font(.system(size: 13, weight: .medium, design: .rounded))
                        .foregroundStyle(WidgetPalette.secondary)
                } else {
                    ForEach(snapshot.upNext.prefix(3), id: \.self) { name in
                        HStack(spacing: 7) {
                            Circle()
                                .fill(WidgetPalette.lime)
                                .frame(width: 6, height: 6)
                            Text(name)
                                .font(.system(size: 13, weight: .semibold, design: .rounded))
                                .foregroundStyle(.white)
                                .lineLimit(1)
                        }
                    }
                }
                Spacer(minLength: 0)
                Text(snapshot.dueCount > 0 ? "Start review →" : "Open Today →")
                    .font(.system(size: 12, weight: .bold, design: .rounded))
                    .foregroundStyle(WidgetPalette.lime)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var circular: some View {
        Gauge(value: snapshot.goalProgress) {
            Image(systemName: "bolt.fill")
        } currentValueLabel: {
            Text("\(snapshot.dueCount)")
        }
        .gaugeStyle(.accessoryCircularCapacity)
    }

    private var rectangular: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text("GraphRecall")
                .font(.headline)
                .widgetAccentable()
            Text(dueLine)
            Text(footer)
                .foregroundStyle(.secondary)
        }
    }
}

#Preview(as: .systemMedium) {
    DueCardsWidget()
} timeline: {
    DueCardsEntry(date: .now, snapshot: .placeholder)
    DueCardsEntry(date: .now, snapshot: .empty)
}
