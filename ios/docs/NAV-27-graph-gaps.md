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
| Chrome | Controls / Inspector / modals | Liquid Glass controls panel, compact + expandable concept card, merge bar, create sheet, suggest-links sheet |

## Visual design (iOS)

| Web | iOS | Why |
| --- | --- | --- |
| Bloom glow | Removed | Glow read as flashing and hid structure |
| 8k-point rotating galaxy | Removed | Visual noise behind small nodes |
| Community wireframe boxes + glow spheres | Removed; "Color by → Community" instead | Boxes overlapped and tinted the scene |
| Neighbours spring toward the selection | Removed; focus dimming instead | Moving nodes are hard to tap |
| Parent / child recolouring on selection | Removed; relationship shown by link colour and in the card | Keeps each node's colour meaning stable |
| Labels on every node, world-sized | Collision-free screen labels with scale LOD: hubs / large / search / merge when browsing; selection + neighbours when focused; zoom + distance cull and a 40–80 cap once the graph is large | Readable at phone zoom; stays usable at thousands of concepts |
| Node size in world units | Clamped to 5–20 px on screen | Distant concepts stay visible and tappable |
| — | Colour by Domain / Mastery / Community | Mastery mode shows weak spots at a glance |
| — | Selection or search dims everything else to 14% | Focus + context |

## Interactions

| Feature | iOS |
| --- | --- |
| Tap concept | Selects it, camera flies to it, compact card appears; scene flattens to 2D focus |
| Card | Compact: name, domain · connections, two-line definition, mastery, **Suggest links** / **Merge…**. Top-right: Quiz, Expand, Close |
| Expanded card | Capped at 58% of the canvas; search and filters collapse to give the graph room; scrolls internally. Full definition, mastery, Notes / Sources / Ask / Details, needs-first / unlocks, suggest links, merge, isolate community, hierarchy, strongest relationships, connected concepts |
| Tap empty space | Deselects |
| Double-tap empty space | Flies to the nearest concept |
| Long-press empty space | Create concept at that world point (`createAt` bridge; NSNumber-safe) |
| + FAB | Always reachable (empty canvas tools, or alone while a card is open). Search “Create this node” also opens the sheet |
| Search | Highlights matches (others dim), "Quiz me", "Create this node" |
| Graph Controls | Domain, min link weight, colour mode, recompute communities, levels, statistics |
| Merge mode | Enter from card → tap orange-ring targets or pick from list → confirm → `POST /api/concepts/merge` |
| Suggest / apply links | Card → sheet → `POST /api/nodes/{id}/suggest-links` then `POST /api/nodes/{id}/link` (strength never sent as null) |

## Create / merge / suggest-links (API ↔ UI)

| Capability | Backend | iOS wiring | Status |
| --- | --- | --- | --- |
| Create concept | `POST /api/nodes` (`name`, `description`, `domain`, `parent_concept_id`, `position`) | Long-press / + FAB / search “Create this node” → `CreateConceptSheet` → `GraphViewModel.createConcept` → reload + optional suggest sheet | **Shipped** |
| Merge concepts | `POST /api/concepts/merge` (`source_ids`, `target_id`) | Card “Merge…” → `GraphMergeBar` + optional `MergeTargetsSheet` → `performMerge` | **Shipped** |
| Suggest links | `POST /api/nodes/{id}/suggest-links` | Card “Suggest links” → `LinkSuggestionsSheet` | **Shipped** |
| Apply links | `POST /api/nodes/{id}/link` | Same sheet → Apply N links → reload | **Shipped** |

Demo / stub graph: create, merge, and apply show a toast and do not hit the API.

## Known limits

1. Labels are still DOM elements (not a GPU atlas). Scale LOD ships: importance + camera-distance cull, stable priority, and a 40–80 browsing cap (selection / neighbours / search / merge always kept). Tens of thousands of concepts may still want a texture atlas later.
2. Communities recompute UI calls the API; if the route is down the toast says so and the current communities stay.
3. Suggest-links depends on the LangGraph workflow + LLM; slow or empty results are surfaced in the sheet, not as a crash.
4. True web bloom / galaxy / community boxes stay deferred (by design for phone readability).
5. Do **not** claim full web 1:1 until Naveen OK on deferred decorative behaviours.

## Recent polish (this slice)

- Label LOD at scale (`Tools/graph3d` → `WebAssets/graph3d.bundle.js`): browsing shows hubs / large / nearby / search / merge only; zoom + distance cull when node count is high; 40–80 cap with stable priority; focus keeps selection + neighbours labeled.
- Compact card surfaces Suggest + Merge (no expand required).
- + FAB stays available while a concept card is open.
- `createAt` bridge reads WK `NSNumber` coordinates correctly.
- Apply-links body always sends a concrete `strength` (Pydantic rejects null).
- After create, selection falls back to name match if the response id is missing.
