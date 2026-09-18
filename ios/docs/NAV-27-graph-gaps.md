# NAV-27 — Graph visualizer (web ↔ iOS)

Owner: Coder Bot 3 · Branch: `feat/ios-liquid-glass` · Issue: [NAV-27](https://linear.app/usnaveen/issue/NAV-27)

The iOS Graph tab started as a one-to-one port of the web 3D GraphVisualizer. After trying it on a phone,
Naveen asked for something calmer and more practical, so iOS keeps the web's 3D graph and feature set
but drops the decorative effects.

## Stack

| Layer | Web (`main`) | iOS (`feat/ios-liquid-glass`) |
| --- | --- | --- |
| Renderer | React Three Fiber (`GraphVisualizer.tsx`) + UnrealBloom | Three.js 0.182 in WKWebView (`Tools/graph3d/src/graph3d.js` → `WebAssets/graph3d.bundle.js`), no post-processing, renders only when something changes |
| Layout | `ForceSimulation3D` (2D d3 simulation, z from seed) | True 3D d3-force-3d with bounded repulsion and a centre pull, seeded from backend positions scaled ×0.25 |
| Camera | OrbitControls, fly-to-focus | OrbitControls, fly-to-focus at a comfortable distance, fit-to-view on load and reset, focus kept above the bottom card |
| Data | `GET /api/graph3d?limit&offset` | Same, 1000 per page. Each page also returns edges that leave it, so links between pages survive the merge |
| Chrome | Controls / Inspector / modals | Liquid Glass controls panel, compact + expandable concept card, merge bar, create sheet |

## Visual design (iOS)

| Web | iOS | Why |
| --- | --- | --- |
| Bloom glow | Removed | Glow read as flashing and hid structure |
| 8k-point rotating galaxy | Removed | Visual noise behind small nodes |
| Community wireframe boxes + glow spheres | Removed; "Color by → Community" instead | Boxes overlapped and tinted the scene |
| Neighbours spring toward the selection | Removed; focus dimming instead | Moving nodes are hard to tap |
| Parent / child recolouring on selection | Removed; relationship shown by link colour and in the card | Keeps each node's colour meaning stable |
| Labels on every node, world-sized | Collision-free screen labels: important nodes when browsing; the selection and its neighbours when focused | Readable at any zoom without overlap |
| Node size in world units | Clamped to 5–20 px on screen | Distant concepts stay visible and tappable |
| — | Colour by Domain / Mastery / Community | Mastery mode shows weak spots at a glance |
| — | Selection or search dims everything else to 14% | Focus + context |

## Interactions

| Feature | iOS |
| --- | --- |
| Tap concept | Selects it, camera flies to it, compact card appears |
| Card | Compact: name, domain · connections, two-line definition, mastery. Top-right: Quiz, Expand, Close |
| Expanded card | Capped at 58% of the canvas; search and filters collapse to give the graph room; scrolls internally. Full definition, mastery, Notes / Sources / Ask / Details, needs-first / unlocks, suggest links, merge, isolate community, hierarchy, strongest relationships, connected concepts |
| Tap empty space | Deselects |
| Double-tap empty space | Flies to the nearest concept |
| Long-press empty space | Create concept at that point |
| Search | Highlights matches (others dim), "Quiz me", "Create this node" |
| Graph Controls | Domain, min link weight, colour mode, recompute communities, levels, statistics |
| Merge mode | Tap targets (orange rings) or pick from a list, confirm, merge N → 1 |

## Known limits

1. Labels are DOM elements positioned each frame; fine for hundreds of concepts, thousands would want culling by zoom.
