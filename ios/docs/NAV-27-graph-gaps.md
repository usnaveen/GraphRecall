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

## Visual aesthetic

| Item | Web | iOS (before → after this PR) | Status |
| --- | --- | --- | --- |
| Canvas `#07070A` | Yes | Yes → Yes | Matched |
| Accent `#B6FF2E` | Yes | Yes → Yes (selection ring / highlight / controls) | Matched |
| Galaxy background | Three.js points + slow rotation | Flat bg → animated cyan/teal starfield + vignette | Closer (2D stand-in) |
| Domain colors | Backend `DOMAIN_COLORS` | Partial node.color → same palette + hash fallback | Matched |
| Community glow / hulls | `CommunityGlow` + wireframe bounds | None → soft radial hulls + dashed rings | Closer |
| Bloom / emissive nodes | UnrealBloomPass | Flat circles → radial glow + emissive fill | Closer |
| Link type colors | PREREQUISITE_OF / etc. | Uniform lime → REL_COLORS map | Matched |
| Link particles | No (solid lines) | Yes (kept; web uses Line thickness) | Differ (acceptable) |
| True 3D orbit / Z depth | Yes | 2D pan/zoom only | **Remaining** |

## Interactions

| Feature | Web | iOS | Status |
| --- | --- | --- | --- |
| Search + highlight | Yes | Liquid Glass search → highlight set | Matched (chrome) |
| Domain filter | Controls panel | None → in-WebView Controls | Matched (in WebView) |
| Min relationship weight | Slider | None → slider in WebView | Matched (in WebView) |
| Communities toggle | On/Off + Recompute API | None → On/Off + hull reheat | Partial (no `POST /communities/recompute` yet) |
| Inspector (links, quiz, merge, notes) | Full `Inspector.tsx` | Compact detail card | **Remaining** |
| NotePanel | Split pane + chunks | Missing | **Remaining** |
| Create node / link suggestions | Modals + `/api/nodes` | Missing | **Remaining** |
| Merge mode | Multi-select + `/api/concepts/merge` | Missing | **Remaining** |
| Demo / empty fallback | Error UI | Stub 5 nodes → richer 10-node demo + communities badge | Improved |

## Data shape (`/api/graph3d`)

Web `adaptGraphData` and iOS `Graph3DResponse` both consume:

- `nodes[]`: `id`, `name`, `definition`, `domain`, `size`, `color`, optional `x/y/z`, mastery fields
- `edges[]`: `source`, `target`, `relationship_type`, `strength`
- `clusters[]`: domain aggregates with colors
- `communities[]`: `id`, `title`, `level`, `parent`, `entity_ids`, `size`, `summary`

iOS now forwards `communities` into the WebView payload (was nodes/links only).

Related routes:

- `GET /api/graph3d/focus/{concept_id}`
- `GET /api/graph3d/search?query=`
- `POST /api/graph3d/communities/recompute`
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

## Gaps remaining after this PR (honest)

1. **Not true 3D** — still 2D force-graph inside WKWebView (no OrbitControls / Z spring).
2. **Inspector / NotePanel / Create / Merge / Link suggestions** — not ported; Liquid Glass detail card only.
3. **Communities recompute** — UI reheats layout only; does not call backend yet.
4. **Bloom / galaxy** — canvas approximations, not Three.js post-processing.
5. Do **not** claim full 1:1 until Naveen signs off on deferred Controls/Inspector/NotePanel behaviors.

## Files touched

- `ios/WebAssets/graph_force.html`, `graph_force.css`, `graph_force_boot.js` (+ mirrored under `ios/GraphRecall/Resources/`)
- `ios/GraphRecall/Features/Graph/GraphForceWebView.swift`, `GraphViewModel.swift`
- `ios/GraphRecall/Networking/Models/GraphModels.swift`
- Xcode resources entry for `graph_force.css`
