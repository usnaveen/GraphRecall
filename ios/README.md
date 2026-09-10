# GraphRecall iOS (Liquid Glass)

Native **SwiftUI** client for GraphRecall on **iOS 26+**, using Apple **Liquid Glass** (`.glassEffect` / `GlassEffectContainer`) to match the web `liquid-glass-dock` look.

## Bundle ID
`com.usnaveen.graphrecall`

## Open / generate
```bash
cd ios
xcodegen generate
open GraphRecall.xcodeproj
```

## Layout
- `DesignSystem/` — colors (`#07070A`, `#B6FF2E`), type, glass helpers
- `Components/LiquidDock` — 5-tab floating glass dock (Feed / Graph / Create / Assistant / Profile)
- `Networking/APIClient` — FastAPI client (auth, feed, graph, chat stream request helper)
- `Features/*` — placeholders for Bot 1 (Feed/SM-2) and Bot 3 (Chat/Graph)

## Backend
Point `GRAPHRECALL_API_BASE` at your FastAPI host (default `http://127.0.0.1:8000` on simulator).

## Split
- **Coder Bot 2**: shell + DesignSystem + dock + API client (this PR)
- **Coder Bot 1**: Feed / quiz / SM-2 + offline
- **Coder Bot 3**: Chat SSE + graph viz
