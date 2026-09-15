// Renders the 1024pt GraphRecall app icon: a lime → cyan constellation on the #07070A canvas.
//
//     swift ios/Tools/make_app_icon.swift ios/GraphRecall/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png

import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let size = 1024
let output = CommandLine.arguments.dropFirst().first ?? "AppIcon.png"
let space = CGColorSpace(name: CGColorSpace.sRGB)!

guard let ctx = CGContext(
    data: nil,
    width: size,
    height: size,
    bitsPerComponent: 8,
    bytesPerRow: 0,
    space: space,
    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
) else { fatalError("Could not create bitmap context") }

func color(_ hex: UInt32, _ alpha: CGFloat = 1) -> CGColor {
    CGColor(
        srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
        green: CGFloat((hex >> 8) & 0xFF) / 255,
        blue: CGFloat(hex & 0xFF) / 255,
        alpha: alpha
    )
}

func glow(_ center: CGPoint, radius: CGFloat, hex: UInt32, alpha: CGFloat) {
    let gradient = CGGradient(colorsSpace: space, colors: [color(hex, alpha), color(hex, 0)] as CFArray, locations: [0, 1])!
    ctx.drawRadialGradient(gradient, startCenter: center, startRadius: 0, endCenter: center, endRadius: radius, options: [])
}

let lime: UInt32 = 0xB6FF2E
let cyan: UInt32 = 0x2EFFE6
let canvas: UInt32 = 0x07070A

// Canvas + ambient glow (CoreGraphics origin is bottom-left).
ctx.setFillColor(color(canvas))
ctx.fill(CGRect(x: 0, y: 0, width: size, height: size))
glow(CGPoint(x: 720, y: 760), radius: 640, hex: lime, alpha: 0.22)
glow(CGPoint(x: 280, y: 250), radius: 560, hex: cyan, alpha: 0.16)

// Faint background stars.
var seed: UInt64 = 7
func random() -> CGFloat {
    seed = seed &* 6364136223846793005 &+ 1442695040888963407
    return CGFloat(seed >> 33) / CGFloat(UInt64(1) << 31)
}
for _ in 0..<42 {
    let point = CGPoint(x: 60 + random() * 904, y: 60 + random() * 904)
    let r = 2 + random() * 4
    ctx.setFillColor(color(0xFFFFFF, 0.08 + random() * 0.18))
    ctx.fillEllipse(in: CGRect(x: point.x - r, y: point.y - r, width: r * 2, height: r * 2))
}

struct Node {
    let point: CGPoint
    let radius: CGFloat
    let hex: UInt32
}

let nodes = [
    Node(point: CGPoint(x: 512, y: 780), radius: 92, hex: lime),
    Node(point: CGPoint(x: 258, y: 318), radius: 76, hex: cyan),
    Node(point: CGPoint(x: 766, y: 318), radius: 76, hex: lime),
    Node(point: CGPoint(x: 512, y: 470), radius: 42, hex: 0xFFFFFF),
]
let edges: [(Int, Int, CGFloat)] = [
    (0, 1, 30), (0, 2, 30), (1, 2, 30),
    (3, 0, 14), (3, 1, 14), (3, 2, 14),
]

for (a, b, width) in edges {
    let p1 = nodes[a].point, p2 = nodes[b].point
    ctx.saveGState()
    let path = CGMutablePath()
    path.move(to: p1)
    path.addLine(to: p2)
    ctx.addPath(path)
    ctx.setLineWidth(width)
    ctx.setLineCap(.round)
    ctx.replacePathWithStrokedPath()
    ctx.clip()
    let alpha: CGFloat = width > 20 ? 0.95 : 0.55
    let gradient = CGGradient(
        colorsSpace: space,
        colors: [color(nodes[a].hex, alpha), color(nodes[b].hex, alpha)] as CFArray,
        locations: [0, 1]
    )!
    ctx.drawLinearGradient(gradient, start: p1, end: p2, options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
    ctx.restoreGState()
}

for node in nodes {
    glow(node.point, radius: node.radius * 2.8, hex: node.hex, alpha: 0.42)
    let r = node.radius
    ctx.setFillColor(color(node.hex))
    ctx.fillEllipse(in: CGRect(x: node.point.x - r, y: node.point.y - r, width: r * 2, height: r * 2))
    if node.hex != 0xFFFFFF {
        let core = r * 0.4
        ctx.setFillColor(color(canvas, 0.92))
        ctx.fillEllipse(in: CGRect(x: node.point.x - core, y: node.point.y - core, width: core * 2, height: core * 2))
    }
}

guard let image = ctx.makeImage(),
      let destination = CGImageDestinationCreateWithURL(URL(fileURLWithPath: output) as CFURL, UTType.png.identifier as CFString, 1, nil)
else { fatalError("Could not write \(output)") }
CGImageDestinationAddImage(destination, image, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("Could not finalize \(output)") }
print("Wrote \(output)")
