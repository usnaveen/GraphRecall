# Implementation Plan: Graph UI Enhancements + RAG Fix

## Feature 1: Fix "0 docs • 0 nodes" in Chat RAG

**Root Cause:** `EmbeddingService.embed_batch()` returns `[]` on failure silently. When embeddings fail, chunks save WITHOUT embeddings. Chat's vector search filters `c.embedding IS NOT NULL`, returns 0 results.

**Changes:**
- `backend/services/ingestion/embedding_service.py`: Add retry with exponential backoff (3 attempts), batch splitting on failure (halve batch if too large)
- `backend/graphs/ingestion_graph.py` `embed_node`: Log WARNING when embedding count doesn't match text count; propagate error to state
- `backend/graphs/ingestion_graph.py` `save_chunks_node`: Log WARNING for chunks saved without embeddings
- New: `POST /api/admin/backfill-embeddings` endpoint to re-embed chunks missing embeddings

---

## Feature 2: Node Merge (Backend + Frontend)

**Backend:**
- New endpoint: `POST /api/concepts/merge` in `backend/routers/concepts.py`
  - Body: `{ source_ids: string[], target_id: string }`
  - Logic: Move all relationships from source nodes → target, combine definitions, delete source nodes
  - Neo4j: Transfer relationships with MATCH/CREATE/DELETE pattern
  - PostgreSQL: Update proficiency_scores, flashcards, quizzes concept_id references

**Frontend:**
- `Inspector.tsx`: Add small merge icon (Lucide `Merge`) in header next to close button
- `GraphScreen.tsx`: Add merge state: `mergeMode: boolean`, `mergeSourceId: string | null`, `mergeTargetIds: Set<string>`
- `GraphVisualizer.tsx`: In merge mode, clicking nodes adds to `mergeTargetIds` instead of selecting. Show merge-target nodes with a distinct outline (orange ring)
- New: Merge confirmation bar at bottom of graph showing selected nodes + Confirm/Cancel buttons

---

## Feature 3: Parent/Child Coloring on Selection

**Changes:**
- `GraphScreen.tsx`: When `selectedNode` changes, compute `parentNodeIds` and `childNodeIds` from `connectedLinks` by checking relationship direction:
  - Parent = nodes that have PREREQUISITE_OF → selectedNode (they are prerequisites OF selected)
  - Child = nodes that selectedNode has PREREQUISITE_OF → them
- `GraphVisualizer.tsx`: Pass `parentNodeIds` and `childNodeIds` as props to `GraphScene`
- `Node` component: Override `computedColor` to:
  - Parents: `#3B82F6` (blue)
  - Children: `#10B981` (green/emerald)
  - Selected: existing highlight behavior
  - Others: dimmed (lower emissive intensity)

---

## Feature 4: Connected Nodes Spring Toward Selected

**Changes:**
- `GraphVisualizer.tsx` `GraphScene`: When `selectedNode` changes:
  - Store original positions of connected nodes
  - In `useFrame`, lerp connected nodes toward the selected node (30-50% closer), keeping their relative arrangement
  - On deselect, lerp back to original positions
- This is purely a visual animation, not a force sim change (simpler, more predictable)

---

## Feature 5: Dynamic Domains

**Changes:**
- `frontend/src/components/graph/Controls.tsx`: Remove `DOMAIN_OPTIONS` hardcoded array. Already computes `availableDomains` from graph data — just use that exclusively
- `backend/routers/graph3d.py`: Replace `DOMAIN_COLORS` dict with a deterministic hash-based color generator (HSL with hue from string hash, fixed S/L)
- `frontend/src/lib/graphData.ts` or new `domainColors.ts`: Match the same color generation logic on frontend
- `backend/prompts/extraction.txt`: Remove any domain constraints, let LLM assign freely

---

## Feature 6: Click-to-Navigate (Double-click empty space)

**Changes:**
- `GraphVisualizer.tsx`: Add `onDoubleClick` handler on the invisible background plane
  - Get 3D intersection point via raycaster
  - Animate camera toward that point (reuse existing `focusRef` lerp pattern)
  - Keep `onPointerMissed` (single click) for deselect
- `Canvas`: Add `onDoubleClick` event handling

---

## Feature 7: Notes Side Panel with Split View

**New file:** `frontend/src/components/graph/NotePanel.tsx`
- Renders note/chunk content as formatted text
- Shows images from chunks (from `images` JSONB column)
- Scrollable, with note title header

**Backend:**
- New endpoint: `GET /api/concepts/{concept_id}/notes` in `backend/routers/concepts.py`
  - Query: NoteSource -[EXPLAINS]-> Concept to find linked note_ids
  - Then: Get chunks from PostgreSQL for those note_ids, ordered by chunk_index
  - Return: `{ notes: [{ id, title, chunks: [{ content, images, page_start, page_end }] }] }`

**Frontend layout:**
- `GraphScreen.tsx`: Add state `notePanelOpen: boolean`, `notePanelNoteId: string | null`
- Use CSS flexbox with a draggable divider:
  - Left: graph canvas (flex: adjustable)
  - Divider: 4px drag handle
  - Right: NotePanel (flex: adjustable, default 40%)
- When NotePanel opens, graph container shrinks with CSS transition
- Inspector's "Notes" button triggers this (instead of current resource modal)

---

## Feature 8: Inspector Enhancements

**Changes:**
- `Inspector.tsx`: The description section already exists (line 142-147). Ensure it always shows — if no definition, show "No description available"
- Truncate definition to 2 lines with CSS (`line-clamp-2`)
- Add merge icon button in header row

---

## Feature 9: Verify Min Weight Slider

**Investigation needed:**
- Check that relationship `strength` values vary (not all 1.0)
- The filtering logic in GraphVisualizer line 393 looks correct
- If all strengths are 1.0, the slider won't have visible effect until set to 100%
- May need to check extraction — relationship strengths should increment properly

---

## Implementation Order (Dependencies)

1. **Feature 1** (RAG fix) — Independent, highest priority
2. **Feature 5** (Dynamic domains) — Independent, quick fix
3. **Feature 8** (Inspector enhancements) — Independent, quick
4. **Feature 9** (Verify weight slider) — Investigation only
5. **Feature 3** (Parent/child coloring) — Independent
6. **Feature 4** (Spring animation) — Depends on understanding of #3
7. **Feature 6** (Click-to-navigate) — Independent
8. **Feature 2** (Node merge) — Complex, needs backend + frontend
9. **Feature 7** (Notes side panel) — Most complex, needs backend + new component
