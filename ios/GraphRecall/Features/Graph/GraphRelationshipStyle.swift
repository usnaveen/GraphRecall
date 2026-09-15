import SwiftUI

/// How each relationship type is named and coloured. Kept in step with `REL_META` in
/// ios/Tools/graph3d/src/graph3d.js so the legend matches the scene.
enum GraphRelationshipStyle {
    struct Meta {
        let label: String
        let color: Color
    }

    static let known: [String: Meta] = [
        "PREREQUISITE_OF": Meta(label: "Prerequisite of", color: Color(hex: "#2EFFE6") ?? .cyan),
        "SUBTOPIC_OF": Meta(label: "Subtopic of", color: Color(hex: "#B07CD8") ?? .purple),
        "BUILDS_ON": Meta(label: "Builds on", color: Color(hex: "#F59E0B") ?? .orange),
        "RELATED_TO": Meta(label: "Related to", color: Color(hex: "#E5E7EB") ?? .white),
        "PART_OF": Meta(label: "Part of", color: Color(hex: "#EC4899") ?? .pink),
        "USES": Meta(label: "Uses", color: Color(hex: "#60A5FA") ?? .blue),
        "ORCHESTRATED_BY": Meta(label: "Orchestrated by", color: Color(hex: "#A78BFA") ?? .purple),
        "SUPPORTS": Meta(label: "Supports", color: Color(hex: "#34D399") ?? .green),
    ]

    static func normalized(_ raw: String?) -> String {
        let value = (raw ?? "RELATED_TO").uppercased()
        return value.isEmpty ? "RELATED_TO" : value
    }

    static func color(_ raw: String?) -> Color {
        known[normalized(raw)]?.color ?? (Color(hex: "#E5E7EB") ?? .white)
    }

    static func label(_ raw: String?) -> String {
        let key = normalized(raw)
        if let meta = known[key] { return meta.label }
        return key.replacingOccurrences(of: "_", with: " ").capitalized
    }
}
