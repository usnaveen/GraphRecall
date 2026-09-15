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

## Run on your iPhone
1. Xcode → Settings → Accounts: add your Apple ID so a signing team exists.
2. Copy `Config/Dev.local.xcconfig.example` to `Config/Dev.local.xcconfig` and set `DEVELOPMENT_TEAM`
   and `GR_DEV_SERVER_HOST` (the Mac's address as the phone sees it), then `xcodegen generate`.
3. Pair the phone with Xcode once over USB (Window → Devices and Simulators), enable Developer Mode,
   and turn on "Connect via network". After that, builds install over Wi-Fi or the phone's hotspot.
4. In the app, Settings → Developer → "Use local Docker backend" points at `GR_DEV_SERVER_HOST:8001`.

## 3D graph
The Graph tab renders a 3D concept graph with Three.js (force layout, orbit camera, colour modes,
focus dimming, merge mode) inside a WKWebView; see `docs/NAV-27-graph-gaps.md`. `project.yml` bundles
`WebAssets/` as resources: `graph3d.html` plus the prebuilt `graph3d.bundle.js`.

The bundle is built from `Tools/graph3d/src/graph3d.js` — rebuild and commit it after editing:
```bash
cd ios/Tools/graph3d
npm install
npm run build
```

## Layout
- `DesignSystem/` — colors (`#07070A`, `#B6FF2E`), type, glass helpers
- `Components/LiquidDock` — 5-tab floating glass dock (Feed / Graph / Create / Assistant / Profile)
- `Networking/APIClient` + `ChatSSEClient` — FastAPI client + URLSession SSE for GraphRAG
- `Features/Feed` — SM-2 Today feed + offline queue (Bot 1)
- `Features/Assistant` — Chat streaming UI (Bot 3)
- `Features/Graph` — 3D graph (Three.js in WKWebView) + Liquid Glass controls, inspector, merge and create flows

## Backend
Point `GRAPHRECALL_API_BASE` at your FastAPI host (default `http://127.0.0.1:8000` on simulator).
Set a Bearer token via `APIClient.shared.setAccessToken` once Google auth is wired; without a token, Chat uses a local stub SSE stream and Graph falls back to a demo graph.

## Split
- **Coder Bot 2**: shell + DesignSystem + dock + API client
- **Coder Bot 1**: Feed / quiz / SM-2 + offline
- **Coder Bot 3**: Chat SSE + graph viz
