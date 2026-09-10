# NAV-27 — Graph visualizer gaps (web ↔ iOS)

Owner: Coder Bot 3 · Branch: `feat/ios-liquid-glass` · Issue: [NAV-27](https://linear.app/usnaveen/issue/NAV-27)

Goal: Graph tab must be **one-to-one** with the web GraphVisualizer aesthetic — not a simplified substitute.

## Stack snapshot

| Layer | Web (`main`) | iOS (`feat/ios-liquid-glass`) |
| --- | --- | --- |
| Renderer | React Three Fiber 3D (`GraphVisualizer.tsx`) + bloom/vignette | WKWebView 2D `force-graph` (`graph_force.html` + boot) |
| Background | `GalaxyBackground.tsx` (8k cyan/teal points) | Canvas starfield + vignette (`#07070A`) |
| Accent | `#B6FF2E` | `#B6FF2E` + Liquid Glass chrome around WebView |
| Data | `GET /api/graph3d` (+ focus/search/communities) | `APIClient.fetchGraph()` → `/api/graph3d`, stub on failure |
| Layout | Client `ForceSimulation3D` (d3 3D) | Library force-graph (2D) |
| Inspector | `Inspector.tsx` (right glass panel) | `GraphInspectorPanel` (Liquid Glass bottom panel) |

## Visual aesthetic

| Item | Web | iOS | Status |
| --- | --- | --- | --- |
| Canvas `#07070A` | Yes | Yes | Matched |
| Accent `#B6FF2E` | Yes | Yes (selection ring / highlight / controls) | Matched |
| Galaxy background | Three.js points + slow rotation | Animated cyan/teal starfield + vignette | Closer (2D stand-in) |
| Domain colors | Backend `DOMAIN_COLORS` | Same palette + hash fallback | Matched |
| Community glow / hulls | `CommunityGlow` + wireframe bounds | Soft radial hulls + dashed rings | Closer |
| Bloom / emissive nodes | UnrealBloomPass | Radial glow + emissive fill + inner highlight | Closer |
| Node sizing | `calculateNodeSize(degree, frequency)` | Degree-derived `val` (web formula) + canvas radius scale | Closer |
| Link type colors | PREREQUISITE_OF / etc. | `REL_COLORS` map (incl. USES / SUPPORTS) | Matched |
| Link direction | Line thickness / type color | Directed arrows for prerequisite/builds/part/subtopic; hot particles on selection | Closer |
| Link particles | No (solid lines) | Hot-only particles | Differ (acceptable) |
| True 3D orbit / Z depth | Yes | 2D pan/zoom only | **Remaining** |

## Interactions

| Feature | Web | iOS | Status |
| --- | --- | --- | --- |
| Search + highlight | Yes | Liquid Glass search → highlight set | Matched (chrome) |
| Domain filter | Controls panel | In-WebView Controls | Matched (in WebView) |
| Min relationship weight | Slider | Slider in WebView | Matched (in WebView) |
| Communities toggle | On/Off + Recompute API | On/Off + `POST /api/graph3d/communities/recompute` with graceful fallback + graph reload | Matched (API wired) |
| Community focus | Isolate community | Inspector Focus Community → dim non-members in WebView | Matched (read-only focus) |
| Inspector (links, quiz, merge, notes) | Full `Inspector.tsx` | Rich Glass inspector: description, hierarchy, strongest relationships, connected chips; Quiz/Notes/Links chrome stubs | Closer (**actions** remaining) |
| NotePanel | Split pane + chunks | Missing | **Remaining** |
| Create node / link suggestions | Modals + `/api/nodes` | Missing | **Remaining** |
| Merge mode | Multi-select + `/api/concepts/merge` | Missing | **Remaining** |
| Demo / empty fallback | Error UI | Stub 10-node demo + communities badge | Improved |

## Data shape (`/api/graph3d`)

Web `adaptGraphData` and iOS `Graph3DResponse` both consume:

- `nodes[]`: `id`, `name`, `definition`, `domain`, `size`, `color`, optional `x/y/z`, mastery fields
- `edges[]`: `source`, `target`, `relationship_type`, `strength`
- `clusters[]`: domain aggregates with colors
- `communities[]`: `id`, `title`, `level`, `parent`, `entity_ids`, `size`, `summary`

iOS forwards `communities` (+ `parent`) into the WebView payload.

Related routes:

- `GET /api/graph3d/focus/{concept_id}`
- `GET /api/graph3d/search?query=`
- `POST /api/graph3d/communities/recompute` ← wired from WebView Controls via `graphBridge`
- `POST /api/nodes`, `POST /api/nodes/{id}/suggest-links`, `POST /api/nodes/{id}/link`
- `POST /api/concepts/merge`, `GET /api/concepts/{id}/notes`

## MCP note — tools agents need to find graph content

Agents should treat these **logical tools** as aliases of existing HTTP routes (no separate MCP server required yet):

| Logical tool | Purpose | Existing API |
| --- | --- | --- |
| `graph.query` | Load full / neighborhood graph for viz | `GET /api/graph3d` (`center_concept_id`, `max_depth`, `limit`, `offset`) and `GET /api/graph3d/focus/{concept_id}` |
| `nodes.search` | Typeahead / camera focus candidates | `GET /api/graph3d/search?query=&limit=` |
| `concept.get` | Concept detail + notes for Inspector / NotePanel | Prefer graph node payload; notes via `GET /api/concepts/{concept_id}/notes`. Mutations: `POST /api/concepts/merge`, `DELETE /api/concepts/{id}` |
| `communities.list` | Community metadata + membership for hulls / filters | Communities embedded on `GET /api/graph3d` (`communities[]` with `entity_ids`). Recompute: `POST /api/graph3d/communities/recompute` |

Create / link flows (future Inspector parity): `POST /api/nodes`, `POST /api/nodes/{node_id}/suggest-links`, `POST /api/nodes/{node_id}/link`.

## Closed this pass (after aesthetic milestone `10fd3e9`)

1. **Inspector panel** — `GraphInspectorPanel` mirrors web layout (badges, hierarchy, strongest relationships, connected entities) in Liquid Glass.
2. **Communities recompute** — WebView `commRecompute` → native `POST /api/graph3d/communities/recompute` → reload graph; demo/API failure falls back gracefully with notice.
3. **Visualizer fidelity** — degree-based node sizing (web formula), directed arrows, selection-only particles, community focus dimming, richer glow.

## Gaps remaining (honest)

1. **Not true 3D** — still 2D force-graph inside WKWebView (no OrbitControls / Z spring / Three.js path yet).
2. **Inspector actions** — Quiz / Notes / Links / Merge are chrome-only; NotePanel + API mutations not ported.
3. **Bloom / galaxy** — canvas approximations, not Three.js post-processing.
4. **Create / link suggestions** — not ported.
5. Do **not** claim full 1:1 until Naveen signs off on deferred Controls/Inspector/NotePanel behaviors.

## Files touched (this pass)

- `ios/GraphRecall/Features/Graph/GraphInspectorPanel.swift` (new)
- `ios/GraphRecall/Features/Graph/GraphView.swift`, `GraphViewModel.swift`, `GraphForceWebView.swift`
- `ios/GraphRecall/Networking/APIClient.swift`, `Networking/Models/GraphModels.swift`
- `ios/WebAssets/graph_force_boot.js` (+ mirrored `Resources/`)
- `ios/docs/NAV-27-graph-gaps.md`
