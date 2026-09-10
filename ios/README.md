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
- `Networking/APIClient` + `ChatSSEClient` — FastAPI client + URLSession SSE for GraphRAG
- `Features/Feed` — SM-2 Today feed + offline queue (Bot 1)
- `Features/Assistant` — Chat streaming UI (Bot 3)
- `Features/Graph` — WKWebView force-graph viz (Bot 3)

## Backend
Point `GRAPHRECALL_API_BASE` at your FastAPI host (default `http://127.0.0.1:8000` on simulator).
Set a Bearer token via `APIClient.shared.setAccessToken` once Google auth is wired; without a token, Chat uses a local stub SSE stream and Graph falls back to a demo graph.

## Split
- **Coder Bot 2**: shell + DesignSystem + dock + API client
- **Coder Bot 1**: Feed / quiz / SM-2 + offline
- **Coder Bot 3**: Chat SSE + graph viz
