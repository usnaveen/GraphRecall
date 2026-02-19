# GraphRecall: Complete System Architecture & Interview Guide

> Accurate as of commit `40da633`. Every claim is traceable to source code.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [LLM & Embedding Models](#2-llm--embedding-models)
3. [Document Parsing & Chunking](#3-document-parsing--chunking)
4. [Embedding Pipeline](#4-embedding-pipeline)
5. [Concept Extraction (Graph Node Creation)](#5-concept-extraction-graph-node-creation)
6. [Relationship Creation](#6-relationship-creation)
7. [Duplicate / Overlap Detection](#7-duplicate--overlap-detection)
8. [Community Detection (Global Search)](#8-community-detection-global-search)
9. [Retrieval Pipeline (GraphRAG)](#9-retrieval-pipeline-graphrag)
10. [LangGraph Architecture (All 7 Graphs)](#10-langgraph-architecture-all-7-graphs)
11. [Database Schemas](#11-database-schemas)
12. [Node Merge Feature](#12-node-merge-feature)
13. [Quiz & Flashcard Generation](#13-quiz--flashcard-generation)
14. [Streaming & Chat](#14-streaming--chat)
15. [Future Improvements](#15-future-improvements)

---

## 1. System Overview

```
User Uploads Content (Markdown/PDF)
           |
    FastAPI Backend (Render)
           |
   +-----------------+
   |  LangGraph       |    7 compiled graphs registered in langgraph.json
   |  Supervisor      |    Supervisor routes to: ingestion, chat, research,
   |  Pattern         |    mermaid, content, verify
   +-----------------+
           |
    +------+------+
    |             |
PostgreSQL     Neo4j AuraDB
(pgvector)     (Free Tier)
- notes        - Concept nodes
- chunks       - Relationships (5 types)
- flashcards   - NoteSource nodes
- quizzes      - Community IDs
- communities
```

**Tech Stack:**
- **Backend:** Python 3.11, FastAPI, LangGraph 1.0.7+
- **LLM:** Google Gemini 2.5 Flash (primary), Gemini 2.5 Pro (complex reasoning)
- **Embeddings:** gemini-embedding-001 (#1 on MTEB), 768 dimensions (MRL)
- **Graph DB:** Neo4j AuraDB (free tier, no APOC)
- **Vector DB:** PostgreSQL + pgvector extension
- **Auth:** Google OAuth (no custom JWT)
- **Frontend:** React + TypeScript + React Three Fiber (3D graph)
- **Deployment:** Render (backend), Vercel (frontend)

---

## 2. LLM & Embedding Models

**Source:** `backend/config/llm.py`

### Chat Model
| Parameter | Value | Why |
|-----------|-------|-----|
| Model | `gemini-2.5-flash` | Best cost/intelligence ratio ($0.15/$0.60 per 1M tokens) |
| Context Window | 1M tokens | Handles large textbooks without truncation |
| Built-in Thinking | Yes | 2.5 Flash has reasoning capabilities, no need for separate reasoning model |
| `convert_system_message_to_human` | `True` | Gemini quirk: doesn't natively support system messages |

### Temperature Settings by Use Case
| Use Case | Temperature | Reason |
|----------|-------------|--------|
| Concept Extraction | 0.1-0.2 | Deterministic, factual |
| Query Analysis | 0.0 | Need exact intent classification |
| Chat Response | 0.3 | Slight creativity for natural responses |
| Flashcard Generation | 0.3 | Balanced factual + creative |
| MCQ Generation | 0.5 | More variety in options |
| Mermaid Diagram | 0.1 | Deterministic code generation |
| Synthesis (Conflict) | 0.1 | Deterministic merge decisions |

### Embedding Model
| Parameter | Value | Why |
|-----------|-------|-----|
| Model | `gemini-embedding-001` | #1 on MTEB multilingual benchmark |
| Dimensions | 768 | MRL-trained: 99.74% quality of 3072, 75% less storage |
| Full Dimensions | 3072 | Available but not used (cost/storage tradeoff) |
| Task Types | `retrieval_document` (storage), `retrieval_query` (search) | Asymmetric embedding for better retrieval |

**Why 768 dimensions?** Gemini embedding-001 supports Matryoshka Representation Learning (MRL). At 768 dims, you get 99.74% of the quality of 3072 dims while using 75% less storage in pgvector. The 0.26% quality loss is negligible for our use case.

**Why NOT OpenAI?** Gemini 2.5 Flash provides comparable quality at ~10x lower cost. The embedding model is #1 on MTEB, beating OpenAI's models.

---

## 3. Document Parsing & Chunking

### Parsing (`backend/services/ingestion/parser_service.py`)

**Supported Formats:**
- **Text/Markdown:** Direct UTF-8 parsing
- **PDF:** NOT processed directly. Must be pre-converted via Marker (Google Colab notebook `notebooks/pdf_ocr_colab.ipynb` or local `pdf_ocr.py`). If raw PDF bytes are detected (`%PDF` header), returns error.

**Why Marker, not LlamaParse?** Marker is open-source, runs locally, handles OCR better for textbooks with figures/equations, and doesn't require API keys. LlamaParse was removed.

### Chunking Strategy: Two-Level Hierarchy

**Primary Chunker: `BookChunker`** (`backend/services/book_chunker.py`)

```
BookChunker(max_chars=1400, overlap_ratio=0.15)
```

| Parameter | Value | Reason |
|-----------|-------|--------|
| `max_chars` | 1400 | Parent chunk size. Large enough for LLM context, small enough for focused retrieval |
| `overlap_ratio` | 0.15 | 15% overlap between consecutive chunks to avoid losing context at boundaries |
| `heading_weight` | True | Markdown headings are preserved for hierarchy context |

**How it works:**

1. **Parse lines:** Split markdown into atomic "units" (text paragraphs, headings, figures)
2. **Heading tracking:** Maintains a `heading_stack` — when `## Neural Networks` is seen, it's pushed. When a same-or-higher-level heading appears, the stack pops back. Every unit carries its `headings` context.
3. **Image detection:** Regex `!\[[^\]]*\]\((?P<path>[^)]+)\)` detects images. Looks +-2 lines for figure captions via pattern `^(Figure|Fig\.?|FIGURE)\s+...`
4. **Assemble chunks:** Iterates units, accumulates until `max_chars` exceeded, then flushes. Overlap is computed by keeping trailing units that fit within `max_chars * overlap_ratio` budget (but never carries figures into overlap to avoid duplication).
5. **Output:** `List[Chunk]` where each has `index`, `text`, `images: List[ImageInfo]`, `headings: List[str]`

**Second-Level Split (in `chunk_node`):**

After BookChunker produces parent chunks, each is further split into children:

```python
child_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
```

| Level | Size | Purpose |
|-------|------|---------|
| Parent | ~1400 chars | LLM generation context, stored without embedding |
| Child | ~300 chars | Vector search targets, stored WITH embedding |

**Why parent/child?** This is the "small-to-big" retrieval pattern. We search on small child chunks (high precision) but return the parent chunk (richer context) to the LLM. This is visible in the RAG query:
```sql
SELECT c.content, p.content as parent_content
FROM chunks c
LEFT JOIN chunks p ON c.parent_chunk_id = p.id
```

**Legacy Chunker:** `HierarchicalChunker` in `chunker_service.py` (parent=1000, child=250, overlap=50). Kept for backward compatibility but not used in the current ingestion graph.

---

## 4. Embedding Pipeline

**Source:** `backend/services/ingestion/embedding_service.py`

### Retry Strategy

```python
MAX_RETRIES = 3
MAX_BATCH_SIZE = 50
```

**Three levels of resilience:**

1. **Batch-level retry:** `_embed_with_retry()` tries each batch up to 3 times with exponential backoff (2^attempt seconds: 1s, 2s, 4s)
2. **Batch splitting:** If a full batch (50 texts) fails all 3 retries, falls back to embedding each text individually
3. **Individual retry:** Each individual text also gets 3 retry attempts

```
Texts (N)
  → Split into batches of 50
  → Each batch: 3 retries with backoff
  → If batch fails: fallback to individual (1-by-1)
    → Each individual: 3 retries with backoff
    → If still fails: append [] placeholder → logged as permanent failure
```

**Why MAX_BATCH_SIZE=50?** Gemini embedding API has batch limits. 50 is a safe batch size that avoids rate limiting while still being efficient.

### How Embeddings Are Saved (`save_chunks_node`)

- **Child chunks WITH embedding:** Stored as `cast(:embedding as vector)` in pgvector
- **Child chunks WITHOUT embedding:** Saved without `embedding` column (RAG will skip them)
- **Parent chunks:** Never embedded (they're too large and only used for context expansion)

The embedding is stored as a pgvector literal string: `"[0.123,0.456,...]"`

---

## 5. Concept Extraction (Graph Node Creation)

**Source:** `backend/agents/extraction.py`, `backend/prompts/extraction.txt`

### How Concepts Are Extracted

1. **Content batching** (`extract_concepts_node`): Chunks are grouped into batches of ~25,000 chars each (to fit Gemini's context well). Batches are processed in parallel with `asyncio.Semaphore(5)` to limit concurrency.

2. **Extraction prompt** (`backend/prompts/extraction.txt`): A 122-line structured prompt that instructs the LLM to extract:
   - `name` (shortest canonical form, no parentheticals)
   - `definition` (1-2 sentences)
   - `domain` (subject area)
   - `complexity_score` (1-10)
   - `confidence` (0.0-1.0)
   - `evidence_span` (10-30 word quote from source)
   - `related_concepts` (list of names)
   - `prerequisites` (list of names)
   - `parent_topic` (broader concept)
   - `subtopics` (narrower concepts)

3. **Context-aware extraction** (`extract_with_context`): If existing concepts exist in Neo4j (fetched with `LIMIT 200`), they're appended to the prompt:
   > "Existing concepts: [...]. Do NOT re-extract these. Reference them in related_concepts or prerequisites."

4. **Deduplication**: After all batches complete, concepts are deduped by `name.lower().strip()` in Python.

5. **LLM JSON parsing**: Response is cleaned of markdown code blocks, backslash issues are sanitized via regex, then `json.loads()`.

### How Concepts Become Neo4j Nodes

**Source:** `create_concepts_node` in `ingestion_graph.py`, `create_concept` in `neo4j_client.py`

The `create_concept` method uses **MERGE on normalized name**:

```cypher
MERGE (c:Concept {name_normalized: $name_normalized, user_id: $user_id})
ON CREATE SET
    c.id = $id, c.name = $name, c.definition = $definition,
    c.domain = $domain, c.complexity_score = $complexity_score,
    c.confidence = $confidence, c.created_at = datetime()
ON MATCH SET
    c.name = CASE WHEN size($name) <= size(c.name) THEN $name ELSE c.name END,
    c.definition = CASE WHEN size($definition) > size(coalesce(c.definition, ''))
                   THEN $definition ELSE c.definition END,
    c.confidence = CASE WHEN $confidence > c.confidence THEN $confidence ELSE c.confidence END
```

**Key decisions:**
- **MERGE key:** `name_normalized` + `user_id` (not raw name). Normalization strips parentheticals, lowercases, collapses whitespace: `"Automatic Differentiation (Autograd)"` → `"automatic differentiation"`
- **ON MATCH:** Keeps the SHORTER name (more canonical), LONGER definition, HIGHER confidence
- **Per-user isolation:** All queries include `user_id` filter

### Concept Node Properties

| Property | Type | Description |
|----------|------|-------------|
| `id` | UUID string | Unique identifier |
| `name` | string | Display name (canonical) |
| `name_normalized` | string | MERGE key (lowercase, no parens) |
| `definition` | string | 1-2 sentence definition |
| `domain` | string | Subject area (e.g., "Machine Learning") |
| `complexity_score` | float | 1-10 scale |
| `confidence` | float | 0.0-1.0, how clearly defined in source |
| `user_id` | string | Owner |
| `community_id` | string | Assigned by Louvain (level 0) |
| `created_at` | datetime | Neo4j datetime |

---

## 6. Relationship Creation

**Source:** `create_concepts_node` in `ingestion_graph.py`

### Relationship Types

| Type | Direction | Base Strength | Source | Meaning |
|------|-----------|---------------|--------|---------|
| `RELATED_TO` | concept → concept | 0.8 | extraction | Semantically related |
| `PREREQUISITE_OF` | prereq → concept | 0.9 | extraction | Must understand A before B |
| `SUBTOPIC_OF` | child → parent | 1.0 | extraction | Narrower specialization |
| `BUILDS_ON` | concept → concept | variable | consolidation | Extends or evolves from |
| `PART_OF` | concept → concept | variable | consolidation | Component/element of |
| `EXPLAINS` | NoteSource → Concept | 0.9 | ingestion | Note explains this concept |

### How Relationships Are Created

**Step 1: From LLM Extraction (per-batch)**

The LLM extracts `related_concepts`, `prerequisites`, `parent_topic`, `subtopics` for each concept. In `create_concepts_node`, these are resolved against ALL existing concepts (not just the current batch):

```python
all_name_to_id = {**existing_name_to_id, **name_to_id}  # existing + current batch
```

This enables **cross-note linking**: a concept from Book A can reference a prerequisite from Book B.

**Step 2: Upsert Pattern (Strength Reinforcement)**

```cypher
MERGE (from)-[r:RELATED_TO]->(to)
ON CREATE SET r.strength = $base_strength, r.mention_count = 1
ON MATCH SET r.mention_count = r.mention_count + 1,
             r.strength = CASE WHEN r.strength + $increment > 1.0
                          THEN 1.0 ELSE r.strength + $increment END
```

Every time a relationship is mentioned across different notes, `mention_count` increments and `strength` increases by 0.1 (capped at 1.0). This means relationships that appear in multiple notes become stronger edges in the graph.

**Step 3: Cross-Chunk Consolidation** (`ExtractionAgent.consolidate_relationships`)

A second LLM pass over all extracted concepts discovers relationships that span chunk boundaries. Looks for PREREQUISITE_OF, SUBTOPIC_OF, PART_OF, BUILDS_ON, RELATED_TO. Limited to 50 relationships. This uses a dedicated prompt.

**Step 4: Synthesis Linking** (`link_synthesis_node`)

After synthesis/merge decisions, new concepts are linked to related existing concepts with `RELATED_TO` (strength 0.6, source='synthesis'). Limited to top 5 new × top 3 related.

### Relationship Properties

| Property | Type | Description |
|----------|------|-------------|
| `strength` | float | 0.0-1.0, reinforced on repeated mention |
| `source` | string | "extraction", "synthesis", "consolidation" |
| `mention_count` | int | How many times this edge was independently discovered |
| `created_at` | datetime | First creation |
| `updated_at` | datetime | Last reinforcement |

---

## 7. Duplicate / Overlap Detection

### Level 1: Name Normalization (Neo4j MERGE)

As described in Section 5, `create_concept` uses `name_normalized` as the MERGE key. This catches:
- "Automatic Differentiation (Autograd)" → "automatic differentiation"
- "Gradient Descent Algorithm" → "gradient descent algorithm"
- Extra whitespace, casing differences

### Level 2: Within-Batch Dedup (Python)

After all extraction batches complete, `extract_concepts_node` deduplicates by `name.lower().strip()`:
```python
unique_concepts = {}
for c in concepts:
    key = c["name"].lower().strip()
    if key not in unique_concepts:
        unique_concepts[key] = c
```

### Level 3: Cross-Note Overlap Detection (`find_related_node`)

Compares newly extracted concepts against ALL existing user concepts in Neo4j:

```python
def _word_overlap(s1: str, s2: str) -> float:
    words1 = set(s1.lower().split())
    words2 = set(s2.lower().split())
    return len(words1 & words2) / min(len(words1), len(words2))
```

For each existing concept, checks:
1. `ext_name in name` (substring)
2. `name in ext_name` (reverse substring)
3. `_word_overlap(ext_name, name) > 0.5` (word Jaccard)

**Overlap ratio** = `len(matches) / len(extracted)`. If > 0.3, triggers synthesis path.

### Level 4: Synthesis Agent (LLM-Powered)

**Source:** `backend/agents/synthesis.py`

Uses embedding similarity + LLM analysis:

1. **Embedding comparison:** Pre-computes embeddings for all existing concepts, then for each new concept, finds those with cosine similarity > 0.3 (top 5).
2. **LLM decision:** For each match, asks the LLM to classify:
   - `DUPLICATE` → SKIP (don't create)
   - `CONFLICT` → FLAG_FOR_REVIEW
   - `ENHANCE` → MERGE (update definition)
   - `NEW` → CREATE_NEW

**Similarity thresholds (fallback if LLM fails):**
| Similarity | Decision | Strategy |
|------------|----------|----------|
| > 0.95 | DUPLICATE | SKIP |
| > 0.80 | ENHANCE | MERGE |
| < 0.80 | NEW | CREATE_NEW |

### Level 5: Manual Merge (UI)

The merge feature in the Inspector panel allows users to select nodes and merge them. The backend (`concepts.py /merge`) transfers all relationships from source to target using pure Cypher (no APOC), combines definitions (keeps longer), then deletes the source node.

---

## 8. Community Detection (Global Search)

**Source:** `backend/services/community_service.py`

### Algorithm: Multi-Level Louvain

Uses **NetworkX's `louvain_communities()`** at 3 resolution levels:

| Level | Resolution | Description | Use Case |
|-------|-----------|-------------|----------|
| 0 | 2.0 | Fine-grained (many small communities) | Node-level community_id on Neo4j |
| 1 | 1.0 | Balanced (default) | Global Search map-reduce |
| 2 | 0.5 | Coarse (few large groups) | High-level theme overview |

**Why NOT Neo4j GDS?** AuraDB free tier doesn't include GDS (Graph Data Science). We pull nodes/edges into a NetworkX graph in Python and run Louvain there.

### How Communities Are Built

1. **Fetch graph:** All user's Concept nodes and relationships from Neo4j, with edge weights = `r.strength`
2. **Build NetworkX graph:** `G.add_node()`, `G.add_edge(weight=strength)`
3. **Run Louvain 3x:** At resolutions 2.0, 1.0, 0.5 (seed=42 for determinism)
4. **Title generation:** Top domain + top 3 shortest concept names (e.g., "Machine Learning: SGD, CNN, ReLU")
5. **Parent linking:** For each fine community, find which coarse community contains the majority of its nodes → set `parent_id`
6. **Persist:** Store in PostgreSQL `communities` and `community_nodes` tables. Sync `community_id` to Neo4j Concept nodes (level 0 only).

### Community Summaries (LLM-Generated)

`generate_community_summaries()`:
- For each community, fetches its concepts + internal relationships from Neo4j
- Generates LLM summaries with **level-dependent detail:**
  - Level 0: 2-3 sentences (practical significance)
  - Level 1: 3-4 sentences (theme + interconnections)
  - Level 2: 4-6 sentences (overarching narrative)
- Summaries are cached in PostgreSQL (`communities.summary`). Skips communities that already have summaries unless `force=True`.
- All summaries are generated in **parallel** with `asyncio.gather()`.

---

## 9. Retrieval Pipeline (GraphRAG)

**Source:** `backend/graphs/chat_graph.py` → `get_context_node`

### Step 1: Query Analysis (`analyze_query_node`)

Uses **structured output** (`with_structured_output(QueryAnalysis)`) for 100% reliable extraction:

```python
class QueryAnalysis(BaseModel):
    intent: Literal["explain", "compare", "find", "summarize", "quiz", "path", "general"]
    entities: list[str]
    needs_search: bool
```

### Step 2: Graph Traversal (k-hop)

**How many hops?** Depends on intent:

| Intent | Max Hops | Relationship Types | Why |
|--------|----------|-------------------|-----|
| `path` | 3 | PREREQUISITE_OF only | Learning paths need prerequisite chains |
| `explain` | 1 | All types | Single-hop gives direct context |
| Default | 2 | All types | Balanced context |

**k_hop_context implementation** (`neo4j_client.py`):

```cypher
MATCH (seed:Concept {user_id: $user_id})
WHERE seed.id IN $concept_ids
MATCH path = (seed)-[rels*1..{max_hops}]-(neighbor:Concept)
WHERE ALL(rel IN rels WHERE type(rel) IN $rel_types)
WITH neighbor,
     length(path) AS hops,
     reduce(s = 1.0, rel IN rels | s * coalesce(rel.strength, 0.5)) AS strength_score
WITH neighbor, min(hops) AS hops, max(strength_score) AS strength_score
RETURN ... ORDER BY strength_score DESC, hops ASC
LIMIT $neighbor_limit
```

**Key points:**
- Variable-length path `*1..N` where N is a literal (Neo4j doesn't support parameterized path bounds)
- `strength_score` = product of all edge strengths along the path (multiplicative decay)
- `ALL(rel IN rels WHERE type(rel) IN $rel_types)` filters relationship types
- Nodes ordered by strength (desc) then hops (asc) → closest, strongest connections first
- Max 20 nodes total (seeds + neighbors)
- Confidence filter: `coalesce(c.confidence, 0.8) >= 0.4` (low-confidence concepts excluded from seed)

**Source-scoped filtering:** When `focused_source_ids` is provided (user clicked a source pill in UI), all queries add `AND c.id IN $source_ids`.

### Step 3: Vector Search (RAG)

```sql
SELECT c.id, c.content, c.images, p.content as parent_content,
       n.title, n.id AS note_id,
       1 - (c.embedding <=> cast(:embedding as vector)) as similarity
FROM chunks c
LEFT JOIN chunks p ON c.parent_chunk_id = p.id
JOIN notes n ON c.note_id = n.id
WHERE n.user_id = :user_id
  AND c.chunk_level = 'child'
  AND c.embedding IS NOT NULL
ORDER BY c.embedding <=> cast(:embedding as vector)
LIMIT 5
```

**Key decisions:**
- **Cosine distance** (`<=>` operator) for pgvector similarity
- **child level only** (small chunks for precision)
- **Parent join** (`LEFT JOIN chunks p ON c.parent_chunk_id = p.id`) → returns parent content for richer context
- **Top 5 results** (balanced precision/recall)
- **Null filter** (`c.embedding IS NOT NULL`) skips chunks that failed embedding

### Step 4: Global Search (Map-Reduce)

**Triggered when:** intent is `summarize`/`general` OR no graph concepts found.

Follows **Microsoft GraphRAG Global Search pattern:**

**MAP phase:**
- Gets level-1 community summaries from PostgreSQL
- For each community (up to 12), asks LLM in parallel:
  > "Rate relevance 0-10 and provide a partial answer"
- Filters communities with score > 2

**REDUCE phase:**
- Sorts by relevance score, takes top 5
- Formats as: `**Community Title** (relevance: 8/10, 15 concepts): partial answer`
- Added to `graph_context["global_summary"]`

### Step 5: Response Generation (`generate_response_node`)

Formats all context into a structured system prompt:
- **Knowledge Graph Concepts** (with confidence tags, hop distances)
- **Global Summary** (if map-reduce ran)
- **Relationships** (with strength indicators)
- **Relevant Notes** (with page numbers, image counts)

Intent-specific instructions modify the system prompt (e.g., "Provide a clear explanation" vs "Compare and contrast").

**Citation system:** System prompt instructs LLM to use `[1]`, `[2]` brackets. Sources are passed in order to the frontend as `sourceObjects: [{id, title, content}]`. The frontend parses these with regex and creates clickable buttons.

**Conversation memory:** Last 6 messages included via `MessagesPlaceholder`.

---

## 10. LangGraph Architecture (All 7 Graphs)

**Registered in `langgraph.json`:**

### 10.1 Supervisor Graph (Orchestrator Pattern)

```
START → classify_request → (Command goto) → [ingest|chat|research|mermaid|content|verify] → END
```

- **Pattern:** Supervisor with Command-based routing
- **Router:** `classify_request_node` reads `request_type` from state, returns `Command(goto=req_type)`
- **State mapping:** Each subgraph node is a wrapper function that maps `SupervisorState.payload` → SubgraphState → `SupervisorState.result`
- **State:** `SupervisorState(request_type, user_id, payload, next_node, result, error)`

### 10.2 Ingestion Graph (Most Complex: 13 nodes, 2 conditional edges)

```
START → parse → chunk → extract_concepts → store_note → embed_chunks → save_chunks
  → find_related → [conditional] → synthesize → user_review → [conditional] → create_concepts
                                                                              → END (cancelled)
                  → create_concepts (fast path)
  → link_synthesis → generate_flashcards → generate_quiz → END
```

**LangGraph patterns demonstrated:**
- **Conditional edges:** `route_after_find_related` (overlap detection), `route_after_user_review` (approval)
- **Human-in-the-loop:** `interrupt()` in `user_review_node` pauses graph, `Command(resume=value)` resumes
- **Checkpointing:** MemorySaver (dev) / AsyncPostgresSaver (prod)
- **State:** `IngestionState` with 20+ fields (total=False for partial updates)

**Node execution order is critical:** `store_note` MUST run before `save_chunks` due to FK constraint (`chunks.note_id → notes.id`).

### 10.3 Chat Graph (MessagesState Pattern)

```
START → analyze_query → get_context → generate_response → END
```

- **Pattern:** Linear pipeline with add_messages reducer
- **State:** Uses `Annotated[list[BaseMessage], add_messages]` for automatic message history
- **Tools:** `search_knowledge_graph`, `search_notes` (defined but ToolNode currently bypassed)
- **Structured output:** `with_structured_output(QueryAnalysis)` for intent classification

### 10.4 Research Graph (ReAct Agent)

```
create_react_agent(model, tools, checkpointer)
```

- **Pattern:** Prebuilt ReAct agent with automatic tool-call loop
- **Tools:** `search_existing_knowledge`, `save_research_note`, `search_web` (Tavily)
- **Flow:** LLM decides tool calls → executes → observes → decides next action
- **System prompt:** Check existing knowledge → web search if needed → synthesize → save note

### 10.5 Mermaid Graph (Self-Correction Pattern)

```
START → generate_code → validate_syntax → [valid?] → END
                                        → [invalid] → fix_errors → validate_syntax (loop)
```

- **Pattern:** Generate → Validate → Fix loop (max 3 attempts)
- **Validation:** Bracket balancing, empty code detection
- **Max retries:** 3 (prevents infinite loop)

### 10.6 Content Graph (Parallel/Map-Reduce Pattern)

```
START → plan → [gen_mcq | gen_cards | gen_diagram] → aggregate → END
```

- **Pattern:** Fan-out / Fan-in parallel execution
- **plan → 3 parallel nodes:** MCQ generation, flashcard generation, Mermaid diagram (calls mermaid_graph!)
- **Graph composition:** `gen_diagram` calls `run_mermaid_generation()` — a graph calling another graph

### 10.7 MCP Graph (External Integration)

```
START → call_mcp_server → parse_mcp_result → END
```

- **Pattern:** External service integration (currently mocked)
- **Purpose:** Fact verification via Model Context Protocol
- **Output:** `verdict: "verified"|"incorrect"|"ambiguous"`, `explanation`, `sources`

### Checkpointing Strategy

| Environment | Checkpointer | Persistence |
|-------------|-------------|-------------|
| Development | `MemorySaver` | Volatile (lost on restart) |
| Production | `AsyncPostgresSaver` | Durable (survives restarts) |
| LangGraph Studio | Built-in | Automatic |

Detection: `"langgraph_api" in sys.modules` → skip our checkpointer (Studio provides its own).

---

## 11. Database Schemas

### PostgreSQL Tables

**`notes`**
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | TEXT | Owner |
| title | TEXT | Note title |
| content_text | TEXT | Full markdown content |
| content_hash | TEXT | SHA-256 for deduplication |
| resource_type | TEXT | "book", "notes", "article" |
| created_at | TIMESTAMP | |

**`chunks`**
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| note_id | UUID | FK → notes.id |
| parent_chunk_id | UUID | FK → chunks.id (null for parents) |
| content | TEXT | Chunk text |
| chunk_level | TEXT | "parent" or "child" |
| chunk_index | INT | Order within note |
| page_start | INT | Source page (from Marker) |
| page_end | INT | |
| embedding | VECTOR(768) | pgvector, null for parents |
| images | JSONB | Image metadata array |
| created_at | TIMESTAMP | |

**`communities`**
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | TEXT | |
| title | TEXT | Generated from domain + concept names |
| level | INT | 0=fine, 1=medium, 2=coarse |
| parent_id | UUID | Parent community at higher level |
| size | INT | Number of concepts |
| summary | TEXT | LLM-generated (cached) |

**`community_nodes`** (junction table)
| Column | Type |
|--------|------|
| community_id | UUID |
| user_id | TEXT |
| concept_id | TEXT |

**`flashcards`**, **`quizzes`** — standard tables with user_id, concept_id, content fields.

### Neo4j Schema

**Node Labels:**
- `Concept` — knowledge graph entities (with constraints: unique `id`, indexes on `name`, `domain`)
- `NoteSource` — links notes to concepts (unique `id`)
- `Proposition` — atomic facts (Phase 3, currently disabled)
- `Topic` — topic hierarchy (unique `id`)

**Relationship Types:**
- `PREREQUISITE_OF`, `RELATED_TO`, `SUBTOPIC_OF`, `BUILDS_ON`, `PART_OF` (between Concepts)
- `EXPLAINS` (NoteSource → Concept, with `relevance` property)
- `HAS_PROPOSITION` (NoteSource → Proposition)

**Schema initialization** (`_initialize_schema`):
```cypher
CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE
CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE
CREATE CONSTRAINT note_source_id IF NOT EXISTS FOR (n:NoteSource) REQUIRE n.id IS UNIQUE
CREATE INDEX concept_name IF NOT EXISTS FOR (c:Concept) ON (c.name)
CREATE INDEX concept_domain IF NOT EXISTS FOR (c:Concept) ON (c.domain)
```

---

## 12. Node Merge Feature

**Source:** `backend/routers/concepts.py` POST `/api/concepts/merge`

### How Merge Works

1. **Verify target exists** in Neo4j
2. **For each source concept:**
   a. Query all outgoing relationships (type, props, target node)
   b. For each known rel type, `MERGE` the relationship on the target node
   c. Query all incoming relationships, recreate on target
   d. Delete source's outgoing and incoming rels
   e. Transfer `EXPLAINS` relationships from NoteSource → source to NoteSource → target
   f. Combine definitions (keep the longer one)
   g. Delete the source Concept node
3. Return merged count

**Why pure Cypher (no APOC)?** AuraDB free tier doesn't include APOC procedures. Relationship transfer is done via Python iteration: query rels → loop → CREATE each with type-specific Cypher.

**Known rel types filter:** `["PREREQUISITE_OF", "RELATED_TO", "SUBTOPIC_OF", "BUILDS_ON", "PART_OF"]`

---

## 13. Quiz & Flashcard Generation

### Flashcards (`generate_flashcards_node`)

Two paths:

**Path 1: Proposition-based (if propositions exist, currently disabled)**
- Uses `ContentGeneratorAgent.generate_cloze_from_propositions()`
- Creates cloze deletion cards from atomic facts

**Path 2: Legacy (current)**
- Sends `raw_content[:2000]` + concept names to LLM
- Prompt: "Create 3-5 CLOZE DELETION flashcards. Hide important terms with [___]."
- Temperature: 0.3

### MCQ Generation (`generate_quiz_node`)

- Uses `ContentGeneratorAgent.generate_mcq_batch()`
- 2 MCQs per concept
- Valid concepts must have both `name` and `definition`
- Stored in `quizzes` table with `question_text`, `options_json`, `correct_answer`, `explanation`

### Proposition Extraction (Phase 3 — Disabled)

`PropositionExtractionAgent` extracts atomic facts from each chunk (1 LLM call per chunk). **Currently disabled** in `extract_propositions_node` with comment: "expensive, marginal benefit." Returns empty `{"propositions": []}`.

---

## 14. Streaming & Chat

**Source:** `backend/routers/chat.py` (not fully read, but observed in `AssistantScreen.tsx`)

### SSE Streaming Protocol

```
data: {"type": "status", "content": "Analyzing query..."}
data: {"type": "chunk", "content": "partial response text"}
data: {"type": "done", "sources": [...], "related_concepts": [...], "metadata": {...}}
```

### Source-Scoped Chat

When user clicks a source pill in the UI:
1. `selectedSources` state accumulates source IDs
2. These are sent as `source_ids` in the chat request
3. Backend passes as `focused_source_ids` to ChatState
4. Both graph queries AND vector search filter by these IDs
5. Allows "chatting with a specific book/note"

---

## 15. Future Improvements

### Chunking
- **Semantic chunking:** Use embedding similarity to find natural break points instead of character count
- **Agentic chunking:** LLM decides chunk boundaries based on topic shifts
- **Proposition-based chunking:** Enable the disabled PropositionExtractionAgent for atomic fact extraction

### Retrieval
- **Re-ranking:** Add a cross-encoder re-ranker (e.g., Cohere Rerank) after initial vector retrieval
- **Hybrid search:** Combine BM25 keyword search with vector search (pgvector + tsvector)
- **Adaptive k-hop:** Dynamically adjust hop depth based on graph density around seed nodes
- **Query decomposition:** For complex queries, break into sub-queries and merge results

### Graph
- **Weighted community detection:** Use edge weights more aggressively in Louvain
- **Dynamic community updates:** Incrementally update communities after new ingestion instead of full recompute
- **Graph embedding:** Store node2vec or GraphSAGE embeddings on Concept nodes for graph-aware retrieval
- **Entity resolution:** Use embedding similarity + LLM verification to merge semantically identical concepts across different surface forms

### Embeddings
- **Matryoshka truncation testing:** Benchmark 768 vs 1536 vs 3072 dims on actual retrieval quality
- **Late interaction models (ColBERT):** Token-level embeddings for more precise matching
- **Instruction-tuned embeddings:** Fine-tune on domain-specific data

### LangGraph
- **Tool use in chat:** Enable the ToolNode that's currently bypassed for dynamic tool selection
- **Multi-agent research:** Multiple specialized research agents that collaborate
- **Streaming with LangGraph:** Use `.astream_events()` for real-time node-by-node progress
- **Memory:** Add cross-session user memory using LangGraph's memory store

### Infrastructure
- **Upgrade to AuraDB Pro:** Enables GDS (graph algorithms), APOC, and vector indexes
- **Neo4j vector index:** Store concept embeddings in Neo4j for unified graph+vector search
- **Caching:** Redis for frequently accessed graph queries and community summaries
- **Batch ingestion pipeline:** Process multiple books in parallel with job queue
