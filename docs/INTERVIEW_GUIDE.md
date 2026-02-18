# GraphRecall - Comprehensive Interview-Ready Guide

> A deep-dive into every architectural decision, LangGraph pattern, GraphRAG implementation,
> and system component. Written from an interviewer's perspective.

---

## Status Update (Feb 18, 2026)

This guide has been refreshed for recent production changes:

- Concept dedup now has a **database-level safety net** via Neo4j `MERGE` on `name_normalized + user_id`.
- Ingestion ordering was corrected to be **FK-safe**: `extract_concepts -> store_note -> embed_chunks -> save_chunks`.
- LLM JSON parsing paths were hardened (sanitization for malformed escapes/control chars).
- Graph edge queries now safely handle missing relationship properties (for example `mention_count`) with `coalesce`.
- Frontend navigation changed: **Books/Library moved to Profile** (not a dock tab).
- API surface now includes `/api/knowledge` and totals **12 routers**.

---

## Table of Contents

1. [Project Overview & Elevator Pitch](#1-project-overview--elevator-pitch)
2. [Repository Structure](#2-repository-structure)
3. [Architecture Overview](#3-architecture-overview)
4. [LangGraph Deep-Dive (Primary Focus)](#4-langgraph-deep-dive)
   - 4.1 [Core Concepts Used](#41-core-langgraph-concepts-used)
   - 4.2 [State Definitions & Patterns](#42-state-definitions--patterns)
   - 4.3 [Graph 1: Supervisor Graph (Orchestrator Pattern)](#43-graph-1-supervisor-graph)
   - 4.4 [Graph 2: Ingestion Graph (HITL + Conditional Edges)](#44-graph-2-ingestion-graph)
   - 4.5 [Graph 3: Chat Graph (MessagesState + GraphRAG)](#45-graph-3-chat-graph)
   - 4.6 [Graph 4: Mermaid Graph (Self-Correction / Reflection)](#46-graph-4-mermaid-graph)
   - 4.7 [Graph 5: Research Graph (ReAct Agent)](#47-graph-5-research-graph)
   - 4.8 [Graph 6: Content Graph (Parallel Fan-Out)](#48-graph-6-content-graph)
   - 4.9 [Graph 7: Quiz Graph (Conditional Routing)](#49-graph-7-quiz-graph)
   - 4.10 [Graph 8: Link Suggestion Graph (Simple Pipeline)](#410-graph-8-link-suggestion-graph)
   - 4.11 [Graph 9: MCP Graph (Verification Pipeline)](#411-graph-9-mcp-graph)
   - 4.12 [Checkpointing Strategy](#412-checkpointing-strategy)
   - 4.13 [How Graphs Connect to Each Other](#413-how-graphs-connect-to-each-other)
5. [LangChain Usage](#5-langchain-usage)
6. [GraphRAG Architecture](#6-graphrag-architecture)
   - 6.1 [What is GraphRAG and Why We Use It](#61-what-is-graphrag)
   - 6.2 [Knowledge Graph Schema (Neo4j)](#62-knowledge-graph-schema)
   - 6.3 [Concept Extraction Pipeline](#63-concept-extraction-pipeline)
   - 6.4 [Synthesis & Deduplication](#64-synthesis--deduplication)
   - 6.5 [Hybrid Retrieval (Vector + Keyword + Graph + RRF)](#65-hybrid-retrieval)
   - 6.6 [Community Detection](#66-community-detection)
7. [Adaptive Learning & Quiz Intelligence](#7-adaptive-learning--quiz-intelligence)
8. [FastAPI Layer](#8-fastapi-layer)
9. [Storage Layer](#9-storage-layer)
10. [Key Architectural Decisions & Justifications](#10-key-architectural-decisions)
11. [Interview Questions & Answers](#11-interview-questions--answers)

---

## 1. Project Overview & Elevator Pitch

**GraphRecall** is an AI-powered active recall learning platform that transforms any content (notes, PDFs, articles, URLs) into a personal knowledge graph, then generates spaced-repetition study materials (flashcards, MCQs, fill-in-the-blanks) and provides a GraphRAG-powered chatbot to help users learn effectively.

### The 30-Second Pitch

> "I built GraphRecall, a full-stack AI learning platform that ingests user content, extracts
> concepts using LLM agents, builds a Neo4j knowledge graph, generates study materials via
> spaced repetition, and provides a GraphRAG chatbot. The backend is orchestrated with
> LangGraph using 9 core workflow graphs (+ article ingestion helper graph) demonstrating patterns like supervisor routing,
> human-in-the-loop, self-correction, and ReAct agents. The system uses a dual-database
> architecture - PostgreSQL with pgvector for vector search and Neo4j for relationship
> traversal - enabling hybrid retrieval that combines vector similarity, keyword matching,
> and graph traversal via Reciprocal Rank Fusion (RRF). Quiz generation uses adaptive
> difficulty based on mastery scores, dynamic few-shot prompting from liked questions,
> and semantic deduplication to prevent repetitive content."

### Core User Flow

```
User uploads content (note, PDF, URL)
    |
    v
LangGraph Ingestion Pipeline
    |-- Parse document (Marker-preprocessed markdown + simple text parser)
    |-- Chunk via BookChunker (image-aware, ~1400-char parent chunks + 300-char children)
    |-- Generate embeddings (Gemini embedding-001, 768 dims via MRL)
    |-- Extract concepts (Gemini 2.5 Flash + structured output)
    |-- Detect duplicates (LLM synthesis + normalized-name Neo4j MERGE)
    |-- [OPTIONAL] Human-in-the-loop review (LangGraph interrupt)
    |-- Create Neo4j nodes & relationships
    |-- Generate flashcards & MCQs (adaptive difficulty + semantic dedup)
    |
    v
User studies via Feed (SM-2 spaced repetition)
    |
    v
User asks questions via Chat (Hybrid Retrieval: Vector + Keyword + Graph + RRF)
```

---

## 2. Repository Structure

```
GraphRecall/
|
|-- backend/
|   |-- agents/                    # AI agent implementations
|   |   |-- states.py              #   Shared LangGraph state definitions (9 shared states)
|   |   |-- extraction.py          #   Concept extraction agent (Gemini)
|   |   |-- synthesis.py           #   Duplicate/conflict detection
|   |   |-- content_generator.py   #   MCQ, flashcard generation (adaptive difficulty)
|   |   |-- research_agent.py      #   Web research (Tavily)
|   |   |-- mermaid_agent.py       #   Diagram generation
|   |   |-- scanner_agent.py       #   Lazy quiz scanning
|   |   |-- proposition_agent.py   #   Atomic fact extraction
|   |   |-- graph_builder.py       #   Neo4j graph construction
|   |
|   |-- graphs/                    # LangGraph workflow definitions (9 core + article helper)
|   |   |-- supervisor_graph.py    #   Multi-agent orchestrator
|   |   |-- ingestion_graph.py     #   Content -> concepts pipeline
|   |   |-- chat_graph.py          #   GraphRAG conversation
|   |   |-- research_graph.py      #   ReAct web research
|   |   |-- mermaid_graph.py       #   Self-correcting diagram gen
|   |   |-- content_graph.py       #   Parallel content generation
|   |   |-- quiz_graph.py          #   Quiz gen with conditional research
|   |   |-- link_suggestion_graph.py  # AI-powered graph linking
|   |   |-- mcp_graph.py           #   Claim verification
|   |   |-- checkpointer.py        #   PostgresSaver/MemorySaver config
|   |
|   |-- db/                        # Database clients
|   |   |-- neo4j_client.py        #   Async Neo4j driver (50 conn pool)
|   |   |-- postgres_client.py     #   Async SQLAlchemy + pgvector
|   |   |-- init.sql               #   Consolidated schema (15+ tables, all migrations)
|   |   |-- migrations/            #   17 SQL migration files
|   |
|   |-- routers/                   # FastAPI endpoint handlers (12 routers)
|   |   |-- auth.py, feed.py, chat.py, graph3d.py, ingest_v2.py,
|   |   |-- review.py, uploads.py, notes.py, concepts.py, nodes.py, images.py, knowledge.py
|   |
|   |-- services/                  # Business logic
|   |   |-- feed_service.py        #   Feed generation + semantic dedup + adaptive difficulty
|   |   |-- spaced_repetition.py   #   SM-2 + FSRS algorithms
|   |   |-- community_service.py   #   Louvain clustering + parallel LLM summaries
|   |   |-- retrieval_service.py   #   Hybrid retrieval (Vector + Keyword + Graph + RRF)
|   |   |-- storage_service.py     #   S3/Supabase file uploads
|   |   |-- ingestion/             #   Document processing pipeline
|   |       |-- parser_service.py  #     PDF/DOCX/PPTX -> Markdown
|   |       |-- chunker_service.py #     Hierarchical chunking
|   |       |-- embedding_service.py #   Gemini embeddings (768-dim MRL)
|   |
|   |-- config/                    # Configuration
|   |   |-- llm.py                 #   Centralized LLM model factory (cached)
|   |   |-- observability.py       #   LangSmith tracing
|   |
|   |-- models/                    # Pydantic schemas
|   |   |-- schemas.py             #   Core data models
|   |   |-- feed_schemas.py        #   Feed, quiz, chat models
|   |
|   |-- auth/                      # Authentication
|   |   |-- google_oauth.py        #   Google token verification
|   |   |-- middleware.py          #   get_current_user dependency
|   |
|   |-- main.py                    # FastAPI app entry point
|
|-- langgraph.json                 # LangGraph graph registry
|-- pyproject.toml                 # Python dependencies (uv)
```

### Why This Structure Matters

- **Separation of Concerns**: `graphs/` (orchestration) vs `agents/` (LLM logic) vs `services/` (business logic) vs `routers/` (HTTP)
- **State schemas mostly centralized**: Shared states live in `agents/states.py`; graph-specific local states (for example `LinkSuggestionState`, `ArticleState`, `ChatState`) stay close to their graph files
- **Each graph is self-contained**: Has its own file with nodes, edges, routing, and public interface
- **Database clients are singletons**: `get_neo4j_client()` / `get_postgres_client()` pattern
- **Config centralized**: All model choices in `config/llm.py` — single place to update models and dimensions

---

## 3. Architecture Overview

```
                    +------------------+
                    |   React Frontend |
                    |  (Vite + Three.js)|
                    +--------+---------+
                             |
                    HTTP/SSE via Axios
                             |
                    +--------v---------+
                    |   FastAPI Server  |
                    |  (12 Routers)     |
                    +--------+---------+
                             |
              +--------------+--------------+
              |              |              |
     +--------v---+  +-------v------+  +---v-----------+
     | LangGraph   | | Direct DB    |  | Background    |
     | Workflows   | | Queries      |  | Tasks         |
     | (9 + helper)| | (CRUD ops)   |  | (asyncio)     |
     +-----+------+  +------+-------+  +-------+-------+
           |                 |                  |
     +-----v------+  +------v-------+  +-------v-------+
     |   Agents   |  |              |  |               |
     | (LLM calls)|  |              |  |               |
     +-----+------+  |              |  |               |
           |         |              |  |               |
     +-----v---------v--------------v--v---------+
     |                                            |
     |     +------------+    +-------------+      |
     |     | PostgreSQL |    |   Neo4j     |      |
     |     | + pgvector |    | (AuraDB)    |      |
     |     | (Supabase) |    +-------------+      |
     |     +------------+                         |
     |                                            |
     |     +-------------------+                  |
     |     | Supabase Storage  |                  |
     |     | (S3-compatible)   |                  |
     |     +-------------------+                  |
     +--------------------------------------------+
              External Services:
              - Google Gemini 2.5 Flash (LLM)
              - Gemini embedding-001 (Embeddings, 768-dim MRL)
              - Tavily (Web Search)
              - LangSmith (Tracing)
              - Google OAuth (Auth)
```

### Data Flow Summary

| Action | Flow |
|--------|------|
| **Ingest Note** | Router -> `ingestion_graph` -> ExtractionAgent -> SynthesisAgent -> Neo4j + Postgres |
| **Chat** | Router -> `chat_graph` -> QueryAnalysis -> Hybrid Retrieval (Vector + Keyword + Graph + RRF) -> LLM response |
| **Feed** | Router -> FeedService -> SM-2 algorithm -> due concepts -> ContentGenerator (adaptive difficulty + few-shot) -> cards |
| **3D Graph** | Router -> Neo4j full graph -> NetworkX layout -> JSON response |
| **Link Suggest** | Router -> `link_suggestion_graph` -> Neo4j candidates -> LLM analysis |

---

## 4. LangGraph Deep-Dive

### 4.1 Core LangGraph Concepts Used

Here is every LangGraph concept we use in GraphRecall and WHERE we use it:

| LangGraph Concept | Where Used | Purpose |
|-------------------|------------|---------|
| **StateGraph** | 9 core graphs (+ article helper graph) | Core graph builder - defines nodes, edges, state |
| **TypedDict state** | `agents/states.py` + graph-local state classes | Type-safe state schemas with `total=False` for partial updates |
| **Annotated + add_messages** | `ChatState`, `ResearchState` | Message accumulation reducer for conversation history |
| **Conditional edges** | `ingestion_graph`, `mermaid_graph`, `quiz_graph` | Dynamic routing based on state values |
| **Command(goto=...)** | `supervisor_graph` | Programmatic routing from within a node |
| **interrupt()** | `ingestion_graph` | Human-in-the-loop pause for concept review |
| **Checkpointer (MemorySaver)** | `chat_graph`, `ingestion_graph` (dev/local) | In-memory state persistence for conversations/workflows |
| **AsyncPostgresSaver** | `chat_graph`, `ingestion_graph` (prod/local with flag) | Production-grade persistent checkpointing |
| **create_react_agent** | `research_graph` | Prebuilt ReAct loop with tool calling |
| **ToolNode** | `chat_graph` (defined, optional) | Prebuilt node for executing tool calls |
| **@tool decorator** | `chat_graph` | LangChain tool definitions for graph/note search |
| **START, END** | All graphs | Entry and exit points |
| **with_structured_output** | `chat_graph`, `extraction.py` | Pydantic model binding for reliable JSON output |
| **langgraph.json** | Root config | Graph registry for LangGraph Platform/Studio |
| **Subgraph composition** | `supervisor_graph` | Invoking compiled subgraphs as wrapper nodes |

### 4.2 State Definitions & Patterns

**All states are defined in `backend/agents/states.py`**. This is a key architectural decision - centralizing state definitions makes it easy to understand data flow across the system.

#### Pattern: `total=False` for Partial Updates

```python
class IngestionState(TypedDict, total=False):
    # Input fields
    user_id: str
    raw_content: str
    # Processing fields
    extracted_concepts: list[dict]
    # Output fields
    created_concept_ids: list[str]
```

**Why `total=False`?** Every node returns ONLY the fields it updates. If a node returns `{"extracted_concepts": [...]}`, only that field is merged into state. This is fundamental to LangGraph's design - nodes are pure functions that return partial state updates.

#### Pattern: `Annotated` with `add_messages` Reducer

```python
class ChatState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    intent: str
    entities: list[str]
    graph_context: dict
    rag_context: list[dict]
```

**Why `add_messages`?** Without a reducer, returning `{"messages": [new_msg]}` would REPLACE the entire message list. The `add_messages` reducer APPENDS new messages instead. This is how LangGraph maintains conversation history across turns.

#### Complete State Map

| State | Graph | Key Fields | Special Features |
|-------|-------|------------|------------------|
| `SupervisorState` | supervisor | request_type, payload, result | Command-based routing |
| `IngestionState` | ingestion | raw_content, extracted_concepts, synthesis_decisions, needs_synthesis | HITL interrupt, conditional edges |
| `ReviewSessionState` | review (planned graph) | due_cards, responses, session_completed | Review-session workflow scaffold |
| `ChatState` | chat | messages (add_messages), intent, entities, graph_context, rag_context | Message reducer, checkpointing |
| `MermaidState` | mermaid | current_code, validation_error, attempt_count | Self-correction loop |
| `ResearchState` | research | messages (add_messages), topic | ReAct agent |
| `ContentState` | content | topic, mcqs, term_cards, diagram, final_pack | Parallel fan-out |
| `QuizState` | quiz | topic, resources, needs_research | Conditional branching |
| `MCPState` | mcp | claim, verdict, explanation | Simple pipeline |
| `LinkSuggestionState` | link_suggestion | node_id, candidates, links | Local state in `link_suggestion_graph.py` |
| `ArticleState` | article | url, html_content, markdown_content, ingestion_result | URL fetch/parse/ingest helper graph |

---

### 4.3 Graph 1: Supervisor Graph (Orchestrator Pattern)

**File**: `backend/graphs/supervisor_graph.py`
**Pattern**: Multi-agent orchestration via **Command-based routing**

```
START --> classify_request_node
              |
              |-- Command(goto="ingest")  --> call_ingestion_subgraph --> END
              |-- Command(goto="chat")    --> call_chat_subgraph     --> END
              |-- Command(goto="research")--> call_research_subgraph --> END
              |-- Command(goto="mermaid") --> call_mermaid_subgraph  --> END
              |-- Command(goto="content") --> call_content_subgraph  --> END
              |-- Command(goto="verify")  --> call_verify_subgraph   --> END
```

#### Key Implementation Details

**Command-based routing** (instead of `add_conditional_edges`):

```python
def classify_request_node(state: SupervisorState) -> Command:
    req_type = state.get("request_type", "unknown")
    if req_type not in ["ingest", "chat", "research", "mermaid", "content", "verify"]:
        return Command(goto=END, update={"error": f"Unknown: {req_type}"})
    return Command(goto=req_type)
```

**Why `Command` instead of conditional edges?** `Command` lets you both route AND update state in a single return. It's more explicit and allows the routing logic to live inside the node function rather than in a separate routing function.

**Subgraph invocation via wrapper functions** (state mapping):

```python
async def call_ingestion_subgraph(state: SupervisorState) -> dict:
    payload = state.get("payload", {})
    input_state = {
        "user_id": state.get("user_id"),
        "raw_content": payload.get("content"),
        "title": payload.get("title"),
        "skip_review": payload.get("skip_review", False)
    }
    result = await ingestion_graph.ainvoke(input_state)
    return {"result": {"status": result.get("status"), ...}}
```

**Why wrapper functions?** Each subgraph has a DIFFERENT state schema. The supervisor uses `SupervisorState` (payload, result), while ingestion uses `IngestionState` (raw_content, extracted_concepts). Wrappers handle the state mapping between schemas. This is the "adapter pattern" applied to LangGraph.

#### Interview Talking Point

> "The supervisor graph demonstrates the orchestrator pattern - a central router classifies
> incoming requests and delegates to specialized subgraphs. Each subgraph has its own state
> schema, so wrapper functions act as adapters that map between the supervisor's generic
> payload/result schema and each subgraph's domain-specific schema. We use LangGraph's
> `Command` primitive for routing because it allows both state updates and routing in a
> single return, which is cleaner than separate conditional edge functions."

---

### 4.4 Graph 2: Ingestion Graph (HITL + Conditional Edges)

**File**: `backend/graphs/ingestion_graph.py`
**Pattern**: **Human-in-the-loop** + **Conditional branching** + **Multi-step pipeline**

This is the most complex graph in the system. It demonstrates the most LangGraph features.

```
START
  |
  v
parse_node               -- Parse document (Marker-preprocessed markdown + simple text parser)
  |
  v
chunk_node               -- BookChunker (image-aware, ~1400-char parent chunks)
  |                          Child chunks created with RecursiveCharacterTextSplitter (~300 chars)
  v
extract_concepts_node    -- LLM extracts concepts + relationships (Gemini 2.5 Flash)
  |                          CONTEXT-AWARE: fetches existing concept names from Neo4j first
  v
store_note_node          -- Save note FIRST (required for chunk FK: chunks.note_id -> notes.id)
  |
  v
embed_node               -- Batch embed ALL child chunks (Gemini embedding-001, 768 dims MRL)
  |                          Uses index_map to track (parent_idx, child_idx) -> flat_index
  v
save_chunks_node         -- Persist parent + child chunks + embeddings to PostgreSQL
  |                          Embeddings stored via: cast(:embedding as vector)
  |
  v
find_related_node        -- Search Neo4j for similar existing concepts
  |                          Uses word overlap matching (threshold > 0.5)
  v
[CONDITIONAL EDGE: route_after_find_related]
  |
  |-- skip_review=False (always) --> synthesize_node --> user_review_node
  |                                                          |
  |                                            (interrupt() pauses here)
  |                                                          |
  |                                  [CONDITIONAL EDGE: route_after_user_review]
  |                                       |                  |
  |                                   approved          cancelled --> END
  |                                       |
  |-- skip_review=True AND               |
  |   no overlap --> create_concepts_node <---+
  |
  v
create_concepts_node  -- Create concepts + ALL relationship types in Neo4j
  |                      (RELATED_TO, PREREQUISITE_OF, SUBTOPIC_OF)
  |                      Also creates NoteSource -> EXPLAINS -> Concept edges
  |                      Cross-note linking: resolves names against ALL existing concepts
  v
link_synthesis_node   -- Cross-reference new concepts <-> related existing ones
  |                      Creates RELATED_TO edges with strength=0.6, source='synthesis'
  v
generate_flashcards_node -- Generate cloze deletion flashcards
  |                         Uses propositions if available, falls back to raw content
  v
generate_quiz_node    -- Generate MCQs (2 per concept)
  |                      Uses ContentGeneratorAgent with structured output
  v
END
```

**13 nodes defined, 2 conditional edges, 1 interrupt point** - `extract_propositions_node` is currently disabled/disconnected for cost optimization, while the active path remains the most complex graph in the system.

#### Key LangGraph Features Demonstrated

**1. Conditional Edges** (routing based on state):

```python
def route_after_find_related(state: IngestionState) -> Literal["synthesize", "create_concepts"]:
    needs_synthesis = state.get("needs_synthesis", False)
    skip_review = state.get("skip_review", False)

    # Force review path if not explicitly skipped
    if not skip_review:
        return "synthesize"  # Always go through review for manual uploads

    # Auto-pilot: only skip synthesis if no overlap
    if needs_synthesis:
        return "synthesize"
    return "create_concepts"

# In graph builder:
builder.add_conditional_edges(
    "find_related",
    route_after_find_related,
    {"synthesize": "synthesize", "create_concepts": "create_concepts"}
)
```

There's also a SECOND conditional edge after user review:
```python
def route_after_user_review(state: IngestionState) -> Literal["create_concepts", "end"]:
    if state.get("user_cancelled", False):
        return "end"    # User cancelled - stop everything
    return "create_concepts"  # User approved - continue

builder.add_conditional_edges(
    "user_review",
    route_after_user_review,
    {"create_concepts": "create_concepts", "end": END}
)
```

**Why TWO conditional edges?** The first routes based on overlap detection + skip_review flag. The second routes based on user decision (approve vs cancel). This gives us three possible paths:
1. **Fast path**: skip_review=True, no overlap -> direct to create_concepts
2. **Review path**: user reviews concepts, approves -> create_concepts
3. **Cancel path**: user reviews concepts, cancels -> END (no concepts created)

**2. Human-in-the-Loop** (`interrupt()`):

```python
async def user_review_node(state: IngestionState) -> dict:
    """Pause for human approval of concept decisions."""
    if state.get("skip_review", False):
        return {"user_approved_concepts": state.get("extracted_concepts", [])}

    synthesis_decisions = state.get("synthesis_decisions", [])

    # This PAUSES the graph execution
    user_response = interrupt({
        "type": "concept_review",
        "decisions": synthesis_decisions,
        "message": "Please review the extracted concepts"
    })

    # Execution resumes here when user responds
    approved = user_response.get("approved_concepts", [])
    return {
        "user_approved_concepts": approved,
        "user_cancelled": user_response.get("cancelled", False)
    }
```

**How does interrupt work?**
1. Graph execution PAUSES at `interrupt()` and returns the interrupt payload to the caller
2. The FastAPI endpoint returns `status: "awaiting_review"` with `thread_id` to the frontend
3. Frontend shows a review UI where user approves/rejects concepts
4. Frontend calls `POST /api/v2/ingest/{thread_id}/approve` with decisions
5. Backend calls `graph.ainvoke(Command(resume=user_response), config)` to RESUME the graph
6. The `interrupt()` call returns the user's response, and execution continues

**Why HITL?** Concept extraction is imperfect. When we detect potential duplicates ("React Hooks" vs "React Custom Hooks"), we want the user to decide: are these the same concept or different ones? This prevents knowledge graph pollution.

**3. Resuming with `Command(resume=...)`** - how the frontend resumes:

```python
async def resume_ingestion(thread_id: str, user_approved_concepts: list[dict],
                           user_cancelled: bool = False) -> dict:
    config = {"configurable": {"thread_id": thread_id}}

    resume_value = {
        "approved_concepts": user_approved_concepts,
        "cancelled": user_cancelled
    }

    # Command(resume=...) sends the value back to the interrupt() call
    result = await ingestion_graph.ainvoke(Command(resume=resume_value), config)
    return result
```

This is a KEY pattern: `Command(resume=resume_value)` tells LangGraph to resume the paused graph and deliver `resume_value` as the return value of the `interrupt()` call.

**4. The `skip_review` Flag** demonstrates a common pattern: making HITL optional. For API-first ingestion (like URL scraping), we auto-approve concepts. For manual uploads, we pause for review.

#### Interview Talking Point

> "The ingestion graph is our most feature-rich workflow. It demonstrates conditional
> routing - when we detect concept overlap above 30%, we route to synthesis and human
> review instead of directly creating concepts. The HITL is implemented with LangGraph's
> `interrupt()` primitive, which pauses execution and returns an interrupt payload. The
> frontend presents a review UI, and when the user approves, we resume the graph with
> their decisions. The graph uses PostgresSaver for checkpointing, so the paused state
> survives server restarts."

---

### 4.5 Graph 3: Chat Graph (MessagesState + GraphRAG)

**File**: `backend/graphs/chat_graph.py`
**Pattern**: **MessagesState** + **Hybrid Retrieval (Vector + Keyword + Graph)** + **Checkpointed conversations**

```
START --> analyze_query --> get_context --> generate_response --> END
```

#### Key LangGraph Features

**1. MessagesState Pattern** (add_messages reducer):

```python
class ChatState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]  # <-- REDUCER
    user_id: str
    intent: str
    entities: list[str]
    graph_context: dict
    rag_context: list[dict]
```

When `generate_response_node` returns:
```python
return {"messages": [AIMessage(content="...")]}
```
The `add_messages` reducer APPENDS this AIMessage to the existing list. Without the reducer, the entire message list would be replaced.

**2. Structured Output** (Pydantic model binding):

```python
class QueryAnalysis(BaseModel):
    intent: Literal["explain", "compare", "find", "summarize", "quiz", "path", "general"]
    entities: list[str]
    needs_search: bool

structured_llm = llm.with_structured_output(QueryAnalysis)
response: QueryAnalysis = await structured_llm.ainvoke(prompt.format_messages())
```

**Why `with_structured_output`?** It uses function calling under the hood to guarantee the LLM returns a valid `QueryAnalysis` object. No regex parsing, no "please return JSON", no hallucinated fields. 100% reliable.

**3. Hybrid Context Retrieval** (`get_context_node`):

The chat graph's context retrieval uses **pgvector cosine similarity** (not ILIKE keyword search) for semantic matching, with a parent chunk LEFT JOIN for richer context:

```python
# Query embedding via Gemini embedding-001 (768 dims MRL)
embeddings_model = get_embeddings()
query_embedding = await embeddings_model.aembed_query(
    query, output_dimensionality=get_embedding_dims()
)
embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"

# Vector search with parent context JOIN
rows = await pg.execute_query("""
    SELECT c.content AS child_content,
           p.content AS parent_content,
           1 - (c.embedding <=> cast(:embedding as vector)) AS similarity
    FROM chunks c
    LEFT JOIN chunks p ON c.parent_chunk_id = p.id
    JOIN notes n ON c.note_id = n.id
    WHERE c.chunk_level = 'child'
      AND c.embedding IS NOT NULL
      AND n.user_id = :user_id
    ORDER BY c.embedding <=> cast(:embedding as vector)
    LIMIT 5
""", {"embedding": embedding_literal, "user_id": user_id})

# Prefer parent content for richer RAG context
content = parent_content if parent_content else child_content
```

**Why vector similarity instead of ILIKE?** ILIKE keyword search misses semantically similar terms (e.g., "ML" vs "machine learning"), produces no relevance ranking, and doesn't leverage our embedding infrastructure. pgvector cosine similarity provides proper semantic matching with ranked results.

**4. Checkpointed Conversations**:

```python
def create_chat_graph():
    builder = StateGraph(ChatState)
    # ... add nodes and edges ...
    checkpointer = get_checkpointer()  # MemorySaver (dev) or PostgresSaver (prod)
    return builder.compile(checkpointer=checkpointer)
```

Usage with thread_id:
```python
config = {"configurable": {"thread_id": thread_id}}
result = await chat_graph.ainvoke(initial_state, config)
```

**How does this enable multi-turn conversations?**
- Turn 1: User asks "What is React?" -> Graph processes, stores messages in checkpoint
- Turn 2: User asks "How does it differ from Vue?" -> Graph loads previous messages from checkpoint, processes with full history
- The `add_messages` reducer ensures new messages are appended to the existing history

**5. Tool Definitions** (defined but optional):

```python
@tool
async def search_knowledge_graph(query: str, entities: list[str] = None) -> str:
    """Search the user's knowledge graph for concepts and relationships."""
    neo4j = await get_neo4j_client()
    result = await neo4j.execute_query(...)
    return formatted_output

chat_tools = [search_knowledge_graph, search_notes]
```

Tools are defined using LangChain's `@tool` decorator but currently the graph goes directly to context retrieval rather than through ToolNode. This is a design decision for reliability - direct context retrieval is more predictable than letting the LLM decide when to call tools.

**6. Retrieving Chat History from Checkpoints**:

```python
async def get_chat_history(thread_id: str) -> list[dict]:
    config = {"configurable": {"thread_id": thread_id}}
    state = await chat_graph.aget_state(config)
    messages = state.values.get("messages", [])
    return [{"role": "human" if isinstance(m, HumanMessage) else "assistant",
             "content": m.content} for m in messages]
```

This uses `aget_state()` to read the persisted state without re-running the graph.

#### Interview Talking Point

> "The chat graph implements a three-step GraphRAG pipeline: analyze the query to extract
> intent and entities, retrieve context from both Neo4j (graph traversal) and PostgreSQL
> (pgvector cosine similarity with parent-child chunk joins), then generate a context-aware
> response. It uses the add_messages reducer for automatic conversation history management,
> and checkpointing for multi-turn persistence. We also support source-scoped retrieval -
> when a user is viewing a specific note, the chat only retrieves context from that note's
> concepts, preventing cross-contamination."

---

### 4.6 Graph 4: Mermaid Graph (Self-Correction / Reflection)

**File**: `backend/graphs/mermaid_graph.py`
**Pattern**: **Self-correction loop** with max retries

```
START --> generate_code --> validate_syntax --[valid]--> END
                              |
                          [invalid]
                              |
                              v
                          fix_errors --> validate_syntax  (loop)
```

#### Key Implementation

**Conditional edge with loop**:

```python
def route_validation(state: MermaidState) -> Literal["end", "fix"]:
    error = state.get("validation_error")
    attempt = state.get("attempt_count", 1)
    if not error:
        return "end"
    if attempt >= 3:  # Prevent infinite loops
        return "end"
    return "fix"

builder.add_conditional_edges(
    "validate_syntax",
    route_validation,
    {"end": END, "fix": "fix_errors"}
)
builder.add_edge("fix_errors", "validate_syntax")  # Loop back
```

**Why a self-correction loop?** LLMs generate syntactically invalid Mermaid code ~15% of the time (unbalanced brackets, hallucinated syntax). Rather than returning broken diagrams, we validate and fix. The `attempt_count` prevents infinite loops - after 3 attempts, we return the best-effort code with an error flag.

#### Interview Talking Point

> "The Mermaid graph demonstrates the self-correction pattern. After generating diagram code,
> we validate the syntax. If invalid, we loop back to a fix node that receives the error
> message and attempts correction. We cap retries at 3 to prevent infinite loops. This is
> a common reliability pattern in LLM applications - generate, validate, fix."

---

### 4.7 Graph 5: Research Graph (ReAct Agent)

**File**: `backend/graphs/research_graph.py`
**Pattern**: **Prebuilt ReAct agent** with multiple tools

This uses `create_react_agent` - a prebuilt LangGraph graph. No manual nodes or edges needed.

```python
from langgraph.prebuilt import create_react_agent

def create_research_agent():
    tools = [search_existing_knowledge, save_research_note]
    if TAVILY_AVAILABLE:
        tools.append(search_web)  # Optional web search

    model = get_chat_model(temperature=0.3)
    checkpointer = get_checkpointer()

    return create_react_agent(model=model, tools=tools, checkpointer=checkpointer)
```

**Three tools available**:

| Tool | Purpose | Implementation |
|------|---------|----------------|
| `search_existing_knowledge` | Search Neo4j concepts + PostgreSQL notes FIRST | Prevents redundant web searches |
| `search_web` | Tavily web search (only if installed) | Fills knowledge gaps |
| `save_research_note` | Save synthesized findings as a note | Persists research to DB |

**The ReAct loop**:
1. LLM receives system prompt with a prescribed workflow (search existing -> web research -> save)
2. LLM decides whether to call a tool or respond
3. If tool call: LangGraph executes the tool, feeds result back to LLM
4. LLM reasons about the result and decides next action
5. Repeat until LLM responds without a tool call

**Why `create_react_agent` instead of a custom StateGraph?** The research workflow is inherently dynamic - the agent needs to decide HOW MANY searches to do, WHAT to search for, and WHEN to stop. A fixed StateGraph can't handle this flexibility. ReAct lets the LLM drive the loop.

---

### 4.8 Graph 6: Content Graph (Parallel Fan-Out)

**File**: `backend/graphs/content_graph.py`
**Pattern**: **Plan -> Parallel fan-out -> Fan-in -> Aggregate**

```
START --> plan_content (fetch concepts from Neo4j)
              |
              |-- edge to gen_mcq
              |-- edge to gen_cards        (3 edges from plan = parallel fan-out)
              |-- edge to gen_diagram
              |
              v              v              v
          gen_mcq      gen_cards      gen_diagram
              |              |              |
              |-- edge to aggregate
              |-- edge to aggregate        (3 edges to aggregate = fan-in)
              |-- edge to aggregate
              |
              v
          aggregate --> END
```

**Actual graph construction** (the fan-out is real, not simulated):

```python
def create_content_graph():
    builder = StateGraph(ContentState)
    builder.add_node("plan", plan_content_node)
    builder.add_node("gen_mcq", generate_mcq_node)
    builder.add_node("gen_cards", generate_flashcards_node)
    builder.add_node("gen_diagram", generate_diagram_node)
    builder.add_node("aggregate", aggregate_node)

    builder.add_edge(START, "plan")

    # Fan-Out: plan -> [A, B, C] (LangGraph schedules these concurrently)
    builder.add_edge("plan", "gen_mcq")
    builder.add_edge("plan", "gen_cards")
    builder.add_edge("plan", "gen_diagram")

    # Fan-In: [A, B, C] -> aggregate (waits for ALL to complete)
    builder.add_edge("gen_mcq", "aggregate")
    builder.add_edge("gen_cards", "aggregate")
    builder.add_edge("gen_diagram", "aggregate")

    builder.add_edge("aggregate", END)
    return builder.compile()
```

**Graph-calling-graph**: The `gen_diagram` node calls `run_mermaid_generation()` from the Mermaid graph. This demonstrates **subgraph reuse** - the mermaid self-correction graph is invoked as a function from within the content graph.

---

### 4.9 Graph 7: Quiz Graph (Conditional Routing + User Consent)

**File**: `backend/graphs/quiz_graph.py`
**Pattern**: **Conditional branching** based on resource availability AND user consent

```
START --> fetch_resources --> check_sufficiency --> [CONDITIONAL]
              |                                        |
              |-- sufficient OR no consent -->  generate_quiz --> END
              |
              |-- insufficient AND consent --> research --> generate_quiz --> END
```

**Dual-condition routing** (the interesting part):

```python
def route_by_sufficiency(state: QuizState) -> Literal["research", "generate_quiz"]:
    needs_research = state.get("needs_research", False)
    allow_research = state.get("allow_research", False)  # Default: NO

    if needs_research and allow_research:
        return "research"       # Only if BOTH conditions met
    return "generate_quiz"      # Otherwise, use what we have
```

**Why the `allow_research` flag?** Web searches cost money (Tavily API) and add latency. We don't want to surprise users with web searches they didn't ask for. The frontend passes `allow_research=True` only when the user explicitly enables it. This is a practical production pattern - **gating expensive operations on user consent**.

---

### 4.10 Graph 8: Link Suggestion Graph (Simple Pipeline)

**File**: `backend/graphs/link_suggestion_graph.py`
**Pattern**: **Simple two-step pipeline**

```
START --> fetch_context_node --> generate_links_node --> END
```

The LLM receives the target concept and all candidate concepts, then suggests up to 5 relationships with types (PREREQUISITE_OF, RELATED_TO, SUBTOPIC_OF, etc.) and strength scores (0-1).

---

### 4.11 Graph 9: MCP Graph (Verification Pipeline)

**File**: `backend/graphs/mcp_graph.py`
**Pattern**: **Simple pipeline** for claim verification

---

### 4.12 Checkpointing Strategy

**File**: `backend/graphs/checkpointer.py`

```python
def get_checkpointer(use_postgres: bool = False):
    is_production = os.getenv("ENVIRONMENT") == "production"
    database_url = os.getenv("DATABASE_URL")

    if (is_production or use_postgres) and database_url:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        return AsyncPostgresSaver.from_conn_string(database_url)

    # Development: volatile but fast
    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()
```

**Dual strategy**:
- **Development**: `MemorySaver` (in-memory, fast, no setup, lost on restart)
- **Production**: `AsyncPostgresSaver` (persisted to PostgreSQL, survives restarts)

**Which graphs use checkpointing?**
- `chat_graph`: YES - conversations must persist across turns
- `ingestion_graph`: YES (via thread_id) - HITL pauses must survive
- All other graphs: NO - they're single-run pipelines

---

### 4.13 How Graphs Connect to Each Other

```
                        +------------------+
                        | supervisor_graph  |
                        |  (Orchestrator)   |
                        +--------+---------+
                                 |
                    Command(goto=req_type)
                                 |
          +----------+-----------+-----------+-----------+
          |          |           |           |           |
    +-----v--+  +---v----+  +--v------+  +-v------+  +-v-------+
    |ingest  |  | chat   |  |research |  |mermaid |  | content |
    |_graph  |  | _graph |  |_graph   |  |_graph  |  | _graph  |
    +--------+  +--------+  +---------+  +--------+  +---------+

    Each subgraph has its OWN state schema.
    The supervisor uses wrapper functions to map between states.
```

**Important**: Subgraphs do NOT share state. The supervisor's wrapper functions translate between `SupervisorState.payload` and each subgraph's specific input fields. This is intentional - each graph is independently testable and deployable.

**Graphs that are called directly from FastAPI (NOT through supervisor)**:
- `ingestion_graph` - called by `routers/ingest_v2.py`
- `chat_graph` - called by `routers/chat.py`
- `link_suggestion_graph` - called by `routers/nodes.py`

---

## 5. LangChain Usage

LangChain is used as the **LLM abstraction layer**, not as an orchestration framework (that's LangGraph's job).

### Where LangChain Components Are Used

| Component | Import | Where Used | Purpose |
|-----------|--------|------------|---------|
| `ChatGoogleGenerativeAI` | `langchain_google_genai` | `config/llm.py` | Gemini model wrapper |
| `GoogleGenerativeAIEmbeddings` | `langchain_google_genai` | `embedding_service.py` | Vector embeddings (768-dim MRL) |
| `SystemMessage, HumanMessage, AIMessage` | `langchain_core.messages` | All graphs, agents | Proper message types |
| `ChatPromptTemplate` | `langchain_core.prompts` | `chat_graph.py`, agents | Prompt templating |
| `MessagesPlaceholder` | `langchain_core.prompts` | `chat_graph.py` | Dynamic message injection |
| `@tool` decorator | `langchain_core.tools` | `chat_graph.py` | Tool definitions |
| `with_structured_output` | LLM method | `chat_graph.py`, `extraction.py` | Pydantic model binding |
| `RecursiveCharacterTextSplitter` | `langchain_text_splitters` | `chunker_service.py` | Document chunking |
| `TavilySearchResults` | `langchain_tavily` | `research_graph.py` | Web search tool |
| `add_messages` | `langgraph.graph.message` | `ChatState`, `ResearchState` | Message accumulation reducer |

### LLM Configuration (Centralized & Cached)

```python
# backend/config/llm.py
DEFAULT_CHAT_MODEL = "gemini-2.5-flash"          # Best cost/intelligence ($0.15/$0.60 per 1M tokens)
DEFAULT_REASONING_MODEL = "gemini-2.5-flash"      # Same — 2.5 flash has built-in thinking
DEFAULT_EMBEDDING_MODEL = "models/gemini-embedding-001"  # #1 on MTEB multilingual
DEFAULT_EMBEDDING_DIMS = 768                       # MRL: 99.74% quality of 3072, 75% less storage

@lru_cache(maxsize=8)
def get_chat_model(model=None, temperature=0.3, json_mode=False):
    model_name = model or DEFAULT_CHAT_MODEL
    kwargs = {}
    if json_mode:
        kwargs["model_kwargs"] = {"generation_config": {"response_mime_type": "application/json"}}
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=temperature,
        convert_system_message_to_human=True,
        **kwargs,
    )

@lru_cache(maxsize=1)
def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=DEFAULT_EMBEDDING_MODEL,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )

def get_embedding_dims() -> int:
    return DEFAULT_EMBEDDING_DIMS
```

**Why caching?** Each `ChatGoogleGenerativeAI` instance creates HTTP connection pools. Reusing instances avoids connection overhead on every LLM call.

**Why Gemini 2.5 Flash?** Best cost/intelligence ratio in the Google lineup. $0.15/$0.60 per 1M tokens — 8x cheaper than Pro with 2.5 Flash's built-in thinking/reasoning capabilities.

**Why 768-dim MRL embeddings?** Gemini embedding-001 is trained with Matryoshka Representation Learning (MRL), allowing native dimensionality reduction. 768 dims retains 99.74% of the quality of 3072 dims, with 75% less storage and faster vector operations. The `output_dimensionality` parameter is passed at query time:

```python
# In embedding_service.py
embeddings = await self.embedder.aembed_documents(
    texts, output_dimensionality=self.dims  # 768
)
query_vec = await self.embedder.aembed_query(
    text, output_dimensionality=self.dims   # 768
)
```

---

## 6. GraphRAG Architecture

### 6.1 What is GraphRAG?

**Standard RAG**: Query -> Embed query -> Vector search -> Top-K chunks -> LLM generates answer

**GraphRAG (what we do)**: Query -> Extract entities -> Graph traversal (structured relationships) + Vector search (semantic similarity) + Keyword search (exact matches) -> RRF fusion -> Combined context -> LLM generates answer

**Why GraphRAG over standard RAG?**

| Scenario | Standard RAG | GraphRAG |
|----------|-------------|----------|
| "How does React relate to JavaScript?" | Finds chunks mentioning both | Traverses PREREQUISITE_OF edge from JavaScript to React |
| "What should I learn before Transformers?" | Irrelevant chunks | Follows PREREQUISITE_OF chain: Linear Algebra -> Neural Networks -> Attention -> Transformers |
| "Compare React and Vue" | Chunks about each separately | Finds both nodes, their shared relationships, and differences |
| "Summarize my ML knowledge" | Random ML chunks | Traverses entire ML subgraph with community structure |

### 6.2 Knowledge Graph Schema (Neo4j)

**Nodes**:

```
(:Concept {
    id: UUID,
    name: "React Hooks",
    definition: "Functions that let you use state...",
    domain: "Frontend Development",
    complexity_score: 6,       # 1-10 difficulty
    user_id: UUID,             # User isolation
    community_id: UUID,        # Louvain cluster assignment (Level 0)
    created_at: datetime
})

(:NoteSource {
    id: UUID,
    note_id: UUID,             # Links to PostgreSQL notes table
    summary: "Notes about React...",
    user_id: UUID
})

(:Topic {
    id: UUID,
    name: "Frontend Development"
})
```

**Relationships**:

| Relationship | Direction | Meaning | Example |
|-------------|-----------|---------|---------|
| `PREREQUISITE_OF` | A -> B | Must learn A before B | JavaScript -> React |
| `RELATED_TO` | A <-> B | Semantic association | React <-> Vue |
| `SUBTOPIC_OF` | A -> B | A is part of B | useState -> React Hooks |
| `BUILDS_ON` | A -> B | A extends B (primarily from manual/AI link suggestions) | Custom Hooks -> React Hooks |
| `PART_OF` | A -> B | A is a component of B (manual/AI link suggestions) | Attention Head -> Transformer |
| `EXPLAINS` | NoteSource -> Concept | Note explains concept | Note#1 -> React |

**User Isolation**: Every query includes `WHERE c.user_id = $user_id`. Each user has their own isolated knowledge graph.

### 6.3 Concept Extraction Pipeline

**Agent**: `backend/agents/extraction.py`

1. **Context-aware extraction**: Before extracting, we fetch existing concept names from Neo4j and include them in the prompt. This helps the LLM:
   - Recognize existing concepts (avoid duplicates)
   - Identify relationships to existing concepts
   - Maintain consistent naming

2. **Structured output**: The LLM returns a JSON array of concepts with name, definition, domain, complexity_score, prerequisites, related_concepts, and subtopics.

3. **Cross-chunk consolidation**: After extracting from each chunk, a second LLM pass discovers relationships between ALL extracted concepts (book-level view).

### 6.4 Synthesis & Deduplication

**Agent**: `backend/agents/synthesis.py`

Two-phase matching:

**Phase 1 - Embedding Pre-filter** (O(N+M)):
- Batch-embed all existing concepts (once)
- For each new concept, compute cosine similarity with all existing
- Threshold: similarity > 0.3 -> candidate match

**Phase 2 - LLM Analysis** (only for candidates):
- LLM compares each new concept with its candidate matches
- Returns: DUPLICATE, CONFLICT, ENHANCE, or NEW
- Each decision includes reasoning and merge strategy

**Why two phases?** Embedding comparison is cheap (no LLM calls). We use it to filter from potentially hundreds of existing concepts down to a handful of candidates. Then we use expensive LLM calls only for those candidates.

**Recent hardening (critical)**: dedup now also happens at write-time in Neo4j:

```cypher
MERGE (c:Concept {name_normalized: $name_normalized, user_id: $user_id})
```

`name_normalized` strips parenthetical suffixes and normalizes spacing/case, so variants like `Automatic Differentiation` and `Automatic Differentiation (Autograd)` collapse into one node. This prevents graph fragmentation even if upstream extraction misses a duplicate.

### 6.5 Hybrid Retrieval (Vector + Keyword + Graph + RRF)

**File**: `backend/services/retrieval_service.py`

The retrieval service implements a three-strategy hybrid search merged via **Reciprocal Rank Fusion (RRF)** — the industry-standard algorithm for combining heterogeneous ranked lists.

```
Query
  |
  +---> [Strategy 1] Vector Search (pgvector cosine similarity)
  |         |-- Embed query via Gemini embedding-001 (768 dims MRL)
  |         |-- Search child chunks, JOIN parent for context
  |         |-- Returns: ranked by cosine similarity
  |
  +---> [Strategy 2] Keyword Search (ILIKE fallback)
  |         |-- Extract first 3 significant words (>3 chars)
  |         |-- Build OR pattern matching
  |         |-- Returns: ordered by recency
  |
  +---> [Strategy 3] Graph Search (Neo4j k-hop traversal)
  |         |-- Find seed concepts matching query text
  |         |-- Expand 1-hop to discover related concepts
  |         |-- Returns: seeds (score 0.7) + neighbors (score 0.4)
  |
  v
Reciprocal Rank Fusion (RRF)
  |-- RRF score = sum(1 / (K + rank_i)) across all lists
  |-- K = 60 (standard constant from literature)
  |-- Deduplicate by chunk/concept ID
  |
  v
Top-K fused results with combined context
```

**Implementation**:

```python
class RetrievalService:
    async def search(self, query, user_id, limit=5, include_graph=True):
        # Run all strategies in parallel
        tasks = [
            self._vector_search(query, user_id, limit=limit * 2),
            self._keyword_search(query, user_id, limit=limit),
        ]
        if include_graph:
            tasks.append(self._graph_search(query, user_id, limit=limit))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        # ... handle exceptions gracefully ...

        # Merge with Reciprocal Rank Fusion
        fused = self._reciprocal_rank_fusion(
            vector_results, keyword_results, graph_results
        )
        return fused[:limit]
```

**RRF Algorithm**:

```python
def _reciprocal_rank_fusion(self, *result_lists):
    scores, items = {}, {}
    for result_list in result_lists:
        for rank, item in enumerate(result_list):
            key = str(item.get("id", hash(item.get("content", ""))))
            rrf_score = 1.0 / (RRF_K + rank + 1)
            scores[key] = scores.get(key, 0.0) + rrf_score
            if key not in items or item["_score"] > items[key]["_score"]:
                items[key] = item  # Keep best version

    ranked_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
    return [dict(items[k], _rrf_score=scores[k]) for k in ranked_keys]
```

**Why RRF over simple weighted scoring?** RRF is rank-based, not score-based. Different strategies produce scores on different scales (cosine similarity 0-1, keyword match fixed 0.5, graph seed 0.7). RRF normalizes these by converting to ranks, then fusing. It's robust, parameter-free (only K=60), and used by Elasticsearch, Azure AI Search, and Pinecone.

**Why three strategies?**
- **Vector search** excels at semantic queries ("explain how attention mechanisms work")
- **Keyword search** catches exact terms that embeddings might miss ("ACID" properties)
- **Graph search** provides structural context ("prerequisites of X", related concepts)

### 6.6 Community Detection

**Service**: `backend/services/community_service.py`

Implements **Microsoft GraphRAG-style multi-level community hierarchy**:

1. Export Neo4j graph to NetworkX
2. Run **Louvain community detection** at 3 resolution levels:
   - Level 0: Fine-grained (resolution=2.0, many small communities)
   - Level 1: Default (resolution=1.0, balanced)
   - Level 2: Coarse (resolution=0.5, few large communities)
3. Link parent-child relationships between levels via majority voting
4. Store in PostgreSQL (communities + community_nodes tables)
5. Sync community_id to Neo4j Concept nodes (Level 0)
6. Generate **LLM-powered community summaries** (parallelized via `asyncio.gather`)

**Community Summary Caching**: Summaries are cached — `generate_community_summaries()` skips communities that already have a summary unless `force=True`. This avoids redundant LLM calls on subsequent graph recomputes.

**Parallelized Summary Generation**:
```python
async def generate_community_summaries(self, user_id, force=False):
    communities = await self.get_communities(user_id)
    if not force:
        communities = [c for c in communities if not c.get("summary")]

    # Run all community summaries in parallel
    await asyncio.gather(
        *[_summarize_one(c) for c in communities],
        return_exceptions=True,
    )
```

**Why Louvain?** It's fast, deterministic, and works well on small-medium graphs. Multi-level hierarchy enables both fine-grained node-level queries and coarse global summaries.

---

## 7. Adaptive Learning & Quiz Intelligence

This section covers the intelligent content generation pipeline that makes GraphRecall's study materials adapt to each user's learning progress.

### 7.1 Mastery-Based Adaptive Difficulty

**File**: `backend/agents/content_generator.py`

MCQ generation adjusts difficulty based on the user's proficiency score (0.0-1.0) for each concept:

```python
async def generate_mcq(self, ..., mastery_score=0.0, few_shot_examples=[]):
    base_difficulty = normalize_difficulty(difficulty)

    # Low mastery (< 0.3) → easier questions; High mastery (> 0.7) → harder questions
    if mastery_score > 0.7:
        adjusted_difficulty = min(10, base_difficulty + 2)
    elif mastery_score < 0.3 and mastery_score > 0:
        adjusted_difficulty = max(1, base_difficulty - 2)
    else:
        adjusted_difficulty = base_difficulty
```

The mastery score also changes the **question style** via prompt instruction:
- High mastery (>0.6): "challenge with application/synthesis questions"
- Low mastery (<0.3): "focus on core understanding and recall"
- Medium: "mix recall with some application"

**Where does mastery come from?** The `proficiency_scores` table in PostgreSQL, updated by the spaced repetition system after each review:

```python
async def _get_concept_mastery(self, concept_id, user_id) -> float:
    rows = await self.pg_client.execute_query(
        "SELECT score FROM proficiency_scores WHERE user_id = :user_id AND concept_id = :concept_id",
        {"user_id": user_id, "concept_id": concept_id},
    )
    return float(rows[0]["score"]) if rows else 0.0
```

### 7.2 Dynamic Few-Shot Prompting

Instead of using static examples in MCQ prompts, we inject the user's **liked/saved questions** as few-shot examples:

```python
async def _get_few_shot_examples(self, concept_id, user_id, limit=2):
    rows = await self.pg_client.execute_query("""
        SELECT question_text, options_json, explanation
        FROM quizzes
        WHERE user_id = :user_id AND concept_id = :concept_id
          AND (is_liked = true OR is_saved = true)
        ORDER BY created_at DESC LIMIT :limit
    """, ...)
```

These examples are formatted and injected into the MCQ prompt:
```
Here are examples of high-quality questions for reference (match this style and rigor):
Example 1: {"question": "...", "options": [...], "explanation": "..."}
```

**Why dynamic few-shot?** Static examples produce generic questions. By showing the LLM questions the user specifically liked, the generated questions match the user's preferred style, depth, and format. This is a form of implicit preference learning.

### 7.3 Semantic Quiz Deduplication

**File**: `backend/services/feed_service.py`

Prevents generating near-duplicate questions even when they're phrased differently:

```python
async def _is_duplicate_question(self, question_text, concept_id, user_id, threshold=0.85):
    # Phase 1: Exact text match (cheap)
    if question_text.strip().lower() in existing_texts_lower:
        return True

    # Phase 2: Embedding cosine similarity (catches paraphrases)
    emb_service = await self._get_embedding_service()
    batch_texts = [question_text] + existing_texts
    embeddings = await emb_service.embed_batch(batch_texts)

    query_emb = embeddings[0]
    for existing_emb in embeddings[1:]:
        dot_product = sum(a * b for a, b in zip(query_emb, existing_emb))
        if dot_product > threshold:  # 0.85 = "same question, different words"
            return True
    return False
```

**Why 0.85 threshold?** Lower catches too many false positives (questions about the same concept but different aspects). Higher misses obvious paraphrases. 0.85 empirically catches "What is X?" vs "Define X" while allowing "What is X?" vs "How does X relate to Y?".

**Auto-regeneration on duplicate**: When a duplicate is detected, the feed service automatically regenerates with different parameters:

```python
if is_dup:
    logger.info("MCQ is duplicate, regenerating")
    mcq = await self.content_generator.generate_mcq(
        ..., mastery_score=mastery  # Retry without few-shot for variation
    )
```

### 7.4 MCQ Answer Validation

The content generator validates that exactly one option is marked correct:

```python
# Ensure exactly one correct answer
correct_count = sum(1 for opt in options if opt.is_correct)
if correct_count != 1:
    # Fix: mark first as correct, rest as false
    for i, opt in enumerate(options):
        opt.is_correct = (i == 0)
```

This catches a common LLM failure mode where zero or multiple options are marked correct.

### Interview Talking Point

> "Our quiz generation pipeline uses three intelligence layers beyond basic LLM prompting:
> (1) Mastery-based adaptive difficulty reads the user's proficiency score and adjusts
> question difficulty ±2 levels, plus changes the question style from recall to application.
> (2) Dynamic few-shot prompting injects the user's liked/saved questions into the prompt
> so generated questions match their preferred style. (3) Semantic deduplication uses
> embedding cosine similarity at 0.85 threshold to prevent paraphrased duplicates, with
> automatic regeneration on detection. These three techniques together produce a personalized,
> non-repetitive study experience."

---

## 8. FastAPI Layer

### App Structure

```python
# backend/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB clients, checkpointer. Shutdown: close connections."""
    await get_postgres_client()
    await get_neo4j_client()
    yield
    await close_postgres_client()
    await close_neo4j_client()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, ...)

# 12 routers
app.include_router(auth_router)       # /auth
app.include_router(feed_router)       # /api/feed
app.include_router(chat_router)       # /api/chat
app.include_router(ingest_v2_router)  # /api/v2
app.include_router(knowledge_router)  # /api/knowledge
# ... etc
```

### Key Patterns

**1. Dependency Injection for Auth**:
```python
@router.post("/api/chat")
async def chat(request: ChatRequest, user_id: str = Depends(get_current_user)):
    result = await run_chat(user_id=user_id, message=request.message)
```

**2. SSE Streaming** (Server-Sent Events):
```python
@router.post("/api/chat/stream")
async def stream_chat(...):
    async def event_generator():
        async for event in chat_graph.astream_events(state, config, version="v2"):
            if event["event"] == "on_chat_model_stream":
                yield f"data: {json.dumps({'type': 'chunk', 'content': token})}\n\n"
        yield f"data: {json.dumps({'type': 'done', ...})}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**3. Background Tasks**:
```python
# Fire-and-forget quiz scanning after ingestion
asyncio.create_task(scanner_agent.scan_and_save(content, note_id, user_id))
```

### Complete Endpoint Count

| Router | Prefix | Endpoints |
|--------|--------|-----------|
| auth | /auth | 2 |
| feed | /api/feed | 12 |
| chat | /api/chat | 13 |
| ingest_v2 | /api/v2 | 7 |
| review | /api/review | 7 |
| graph3d | /api/graph3d | 4 |
| uploads | /api/uploads | 7 |
| notes | /api/notes | 2 |
| concepts | /api/concepts | 1 |
| nodes | /api/nodes | 3 |
| images | /api/images | 1 |
| knowledge | /api/knowledge | 1 |
| **Total** | | **~60 endpoints** |

---

## 9. Storage Layer

### Dual Database Architecture

| Database | Type | Purpose | Key Feature |
|----------|------|---------|-------------|
| **PostgreSQL** (Supabase) | Relational + Vector | Notes, users, flashcards, quizzes, chunks, embeddings | pgvector for semantic search (768-dim) |
| **Neo4j** (AuraDB) | Graph | Concepts, relationships, knowledge structure, communities | Cypher queries for graph traversal |

**Why two databases?**
- PostgreSQL is excellent for relational data (users, content, scores) and vector search
- Neo4j is purpose-built for graph traversal (prerequisites, related concepts, learning paths)
- Trying to do graph traversal in PostgreSQL (recursive CTEs) is possible but painful
- Trying to do vector search in Neo4j is possible but less mature than pgvector

### PostgreSQL Schema (Consolidated)

The `init.sql` + `db/migrations/*.sql` pipeline is the source of truth for tables (currently 17 SQL migration files). Key tables:

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `users` | User accounts | google_id, email, settings_json |
| `notes` | Uploaded content | content_text, content_hash, embedding vector(768), resource_type |
| `chunks` | Hierarchical chunks | parent_chunk_id, embedding vector(768), chunk_level, images, page_start/end |
| `propositions` | Atomic facts | content, confidence, is_atomic |
| `proficiency_scores` | Mastery tracking | score (0-1), stability, difficulty_fsrs, next_review_due |
| `flashcards` | Term cards | front_content, back_content, is_liked, is_saved |
| `quizzes` | Generated questions | question_text, options_json, is_liked, is_saved |
| `communities` | Graph clusters | title, level, parent_id, summary |
| `community_nodes` | Cluster membership | community_id, concept_id |
| `chat_conversations` | Chat threads | title, is_saved_to_knowledge |
| `chat_messages` | Chat history | role, content, sources_json |

### PostgreSQL Configuration

```python
engine = create_async_engine(
    database_url,
    pool_size=10,          # Base pool connections
    max_overflow=20,       # Burst capacity
    pool_pre_ping=True,    # Connection health checks
    pool_recycle=3600,     # Recycle every hour
    connect_args={
        "statement_cache_size": 0,  # Required for Supabase
        "ssl": ssl_context          # TLS for cloud
    }
)
```

### Hierarchical Chunking (Parent-Child)

```
Document
  |
  v
Parent Chunks (1000 tokens) -- stored for context
  |
  v
Child Chunks (250 tokens)   -- embedded (768-dim) for precision search
```

**Why hierarchical?**
- **Search on children**: Small chunks = precise vector matches
- **Return parent context**: Large chunks = enough context for LLM generation
- **Query pattern**: Search child embeddings, join with parent for full context

```sql
SELECT c.content AS child_content,
       p.content AS parent_content,
       1 - (c.embedding <=> cast(:embedding as vector)) AS similarity
FROM chunks c
LEFT JOIN chunks p ON c.parent_chunk_id = p.id
WHERE c.chunk_level = 'child'
  AND c.embedding IS NOT NULL
ORDER BY c.embedding <=> cast(:embedding as vector)
```

### Embedding Storage

Embeddings are stored as PostgreSQL `vector(768)` type via pgvector. The embedding literal is constructed as a string array and cast at query time:

```python
embedding_literal = "[" + ",".join(str(x) for x in embedding) + "]"
# In SQL: cast(:embedding as vector)
```

This avoids pgvector dimension mismatch errors and ensures proper type handling.

---

## 10. Key Architectural Decisions & Justifications

### 1. Why LangGraph over plain LangChain chains?

| Aspect | LangChain Chains | LangGraph |
|--------|-----------------|-----------|
| Control flow | Linear or simple branching | Arbitrary graphs with cycles |
| State | Passed through chain | Typed, persistent, checkpoint-able |
| HITL | Not natively supported | `interrupt()` primitive |
| Debugging | Hard to trace | LangSmith integration, step visualization |
| Multi-agent | Complex orchestration needed | Supervisor pattern built-in |

**Decision**: LangGraph gives us HITL (critical for concept review), self-correction loops (Mermaid), and a supervisor pattern (multi-agent routing) that chains can't do cleanly.

### 2. Why Neo4j + PostgreSQL instead of just PostgreSQL?

Graph traversal queries like "find the prerequisite chain for Transformers" require recursive CTEs in PostgreSQL, which are complex and slow. In Neo4j:
```cypher
MATCH path = (prereq)-[:PREREQUISITE_OF*1..5]->(target {name: "Transformers"})
RETURN path
```
One line, fast, readable.

### 3. Why Gemini 2.5 Flash over other models?

| Factor | Gemini 2.5 Flash | GPT-4o | Claude Sonnet |
|--------|-----------------|--------|---------------|
| Cost (input/output per 1M tokens) | $0.15 / $0.60 | $2.50 / $10.00 | $3.00 / $15.00 |
| Built-in thinking/reasoning | Yes (native) | No (separate o1) | No (separate) |
| Structured output | Function calling | Function calling | Tool use |
| Speed | Very fast | Fast | Fast |

**Decision**: Gemini 2.5 Flash is **8-17x cheaper** than alternatives while offering built-in reasoning. For a learning platform generating thousands of quiz questions and processing many documents, cost matters enormously.

### 4. Why 768-dim embeddings via MRL (not 3072)?

| Dimension | Quality (MTEB) | Storage per vector | Index speed |
|-----------|---------------|-------------------|-------------|
| 3072 | 100% (baseline) | 12 KB | Baseline |
| 1536 | ~99.9% | 6 KB | ~1.5x faster |
| **768** | **99.74%** | **3 KB** | **~2x faster** |
| 256 | ~98.5% | 1 KB | ~4x faster |

Gemini embedding-001 supports Matryoshka Representation Learning (MRL), meaning the first N dimensions carry the most information. At 768 dims, we lose only 0.26% quality while gaining 75% storage reduction and significantly faster vector operations. The `output_dimensionality` parameter is passed at query time, so we can change dimensions without re-embedding.

### 5. Why Reciprocal Rank Fusion (RRF) for hybrid search?

| Approach | Pros | Cons |
|----------|------|------|
| Simple weighted average | Easy to implement | Scores are on different scales; requires manual tuning |
| Learned re-ranker | Best quality | Expensive, requires training data |
| **RRF** | **Rank-based (scale-invariant), no tuning, industry standard** | Slightly less optimal than learned re-ranking |

RRF is used by Elasticsearch, Azure AI Search, and Pinecone. The formula `score = sum(1/(K + rank_i))` normalizes across any number of heterogeneous ranked lists. K=60 is the standard value from the original paper.

### 6. Why SM-2 for spaced repetition?

- **Battle-tested**: Used by Anki (100M+ users)
- **Simple**: Just 4 variables (easiness factor, interval, repetition count, last review)
- **Customizable**: We also implemented FSRS v4.5 as an alternative (columns in proficiency_scores)

### 7. Why separate `agents/` from `graphs/`?

- **Agents** = LLM interaction logic (prompts, structured output, retries)
- **Graphs** = Workflow orchestration (nodes, edges, routing, state)
- An agent can be used in multiple graphs (e.g., `ExtractionAgent` is used in both `ingestion_graph` and `review.py`)

### 8. Why parallelized LLM calls?

Multiple places use `asyncio.gather` for concurrent LLM operations:
- **Hybrid retrieval**: Vector + Keyword + Graph searches run in parallel
- **Community summaries**: All communities summarized concurrently
- **MCQ batch generation**: Multiple questions generated simultaneously
- **Map-reduce scoring**: Community relevance scoring parallelized

This reduces latency from O(N * T) to O(T) where T is the slowest single LLM call.

---

## 11. Interview Questions & Answers

### LangGraph Questions

**Q1: Explain how LangGraph differs from LangChain chains. Why did you choose it?**

> LangChain chains are linear pipelines - A calls B calls C. LangGraph is a state machine
> framework where you define nodes (functions) and edges (transitions) forming a directed
> graph. Key differences: (1) LangGraph supports cycles (self-correction loops), (2) it
> has typed persistent state with checkpointing, (3) it supports human-in-the-loop via
> `interrupt()`, and (4) it enables multi-agent patterns like supervisor routing. We chose
> LangGraph because our ingestion pipeline requires conditional branching (synthesis vs
> direct creation), HITL (concept review), and our chat needs checkpointed conversation
> history. None of these are clean with chains.

**Q2: Walk me through how your human-in-the-loop works in the ingestion pipeline.**

> When a user uploads content, the ingestion graph extracts concepts and checks for overlaps
> with existing concepts. If overlap exceeds 30%, it routes to a synthesis node that prepares
> merge/skip/create decisions. Then it hits a `user_review_node` that calls `interrupt()`.
> This pauses the graph and returns the synthesis decisions to the FastAPI endpoint, which
> responds with `status: "awaiting_review"` and a `thread_id`. The frontend shows a review
> UI. When the user approves, the frontend calls POST `/approve` with their decisions. The
> backend resumes the graph using `graph.ainvoke(user_response, config)` with the same
> `thread_id`. The interrupt returns the user's response, and the graph continues creating
> concepts in Neo4j. The paused state is persisted via checkpointing (PostgresSaver in
> production), so it survives server restarts.

**Q3: What is the `add_messages` reducer and why is it important?**

> In LangGraph, when a node returns a state update, the default behavior is to REPLACE
> the field value. For chat messages, we want to APPEND, not replace. The `add_messages`
> reducer (from `langgraph.graph.message`) changes this behavior: when a node returns
> `{"messages": [new_msg]}`, the reducer appends `new_msg` to the existing list instead
> of replacing it. This is how we maintain conversation history across multiple nodes in
> the same graph execution. Without it, the analyze_query node's message would be lost
> by the time we reach generate_response.

**Q4: How do your subgraphs communicate with the supervisor?**

> Each subgraph has its own state schema. The supervisor uses wrapper functions (adapter
> pattern) that translate between `SupervisorState.payload` and each subgraph's specific
> input fields, then translate the subgraph's output back to `SupervisorState.result`.
> The supervisor uses `Command(goto="subgraph_name")` for routing, which is a LangGraph
> primitive that both routes to a node AND can update state in a single return.

**Q5: Explain the self-correction pattern in your Mermaid graph.**

> Generate -> Validate -> Fix loop. The generate node creates Mermaid syntax via LLM.
> The validate node checks for syntax errors (unbalanced brackets, empty output). If
> invalid, a conditional edge routes to the fix node, which sends the error message back
> to the LLM to correct. Then it loops back to validate. We cap at 3 attempts to prevent
> infinite loops. This improves diagram generation reliability from ~85% to ~99%.

### GraphRAG & Retrieval Questions

**Q6: What is GraphRAG and how does your implementation differ from Microsoft's?**

> Standard RAG retrieves chunks by vector similarity. GraphRAG enriches retrieval with
> graph structure. Microsoft's GraphRAG focuses on community summaries for global queries.
> Our implementation focuses on entity-level retrieval with three-strategy hybrid search:
> we use pgvector cosine similarity for semantic matching, ILIKE keyword search as an exact-
> term fallback, and Neo4j graph traversal for structural relationships. These three result
> lists are merged via Reciprocal Rank Fusion (RRF). We also use community detection
> (multi-level Louvain) for both global search summaries and 3D graph visualization.

**Q7: Walk me through a chat query end-to-end.**

> 1. User asks "How does attention relate to transformers?"
> 2. `analyze_query_node`: LLM extracts intent="explain", entities=["attention", "transformers"]
> 3. `get_context_node`: Generates query embedding (768 dims via MRL), then in parallel:
>    - Vector search: pgvector cosine similarity on child chunks with parent JOIN
>    - Graph search: Neo4j seed concept lookup + 1-hop traversal
>    - Keyword search: ILIKE fallback for exact term matches
> 4. Results merged via RRF (K=60), top-5 returned
> 5. `generate_response_node`: Format graph context + chunk context into system prompt,
>    use intent-specific instructions, generate response with citations
> 6. Return response + sources + related_concepts to frontend

**Q8: Explain your hybrid retrieval architecture with RRF.**

> We run three retrieval strategies in parallel via `asyncio.gather`: pgvector cosine
> similarity for semantic matching, keyword ILIKE for exact terms, and Neo4j graph
> traversal for structural relationships. Each strategy returns a ranked list. We merge
> them using Reciprocal Rank Fusion: `score = sum(1/(K + rank_i))` across all lists
> where an item appears. K=60 is the standard constant from the Cormack et al. paper.
> RRF is rank-based rather than score-based, so it handles heterogeneous scales naturally.
> Items appearing in multiple lists get boosted. This is the same algorithm used by
> Elasticsearch and Azure AI Search for hybrid retrieval.

**Q9: Why two databases instead of one?**

> PostgreSQL with pgvector is excellent for vector search and relational data. Neo4j is
> purpose-built for graph traversal. A query like "find all prerequisites for Transformers
> up to 5 hops deep" is a one-line Cypher query but would require complex recursive CTEs
> in PostgreSQL. The trade-off is operational complexity (two databases to manage), but
> the query expressiveness and performance gains are worth it for our use case.

### Model & Embedding Questions

**Q10: Why did you choose 768-dim embeddings instead of the full 3072?**

> Gemini embedding-001 is trained with Matryoshka Representation Learning (MRL), which
> means the first N dimensions carry progressively more information. At 768 dimensions,
> benchmarks show only 0.26% quality loss compared to 3072, but we get 75% less storage,
> faster indexing, and faster similarity computations. The key insight is that MRL is
> native to the model — it's not a post-hoc PCA reduction. We pass `output_dimensionality=768`
> at query time, so we could change to 1536 without re-embedding if we needed slightly
> higher precision.

**Q11: How do you handle embedding dimension consistency across the system?**

> All embedding dimensions are centralized in `config/llm.py` via `DEFAULT_EMBEDDING_DIMS = 768`
> and the `get_embedding_dims()` function. The `EmbeddingService` reads this at init and passes
> it to every `aembed_documents()` and `aembed_query()` call. The database schema uses
> `vector(768)` in both the `chunks` and `notes` tables. SQL embedding storage uses
> `cast(:embedding as vector)` to ensure proper type handling. This centralization means
> changing dimensions requires updating exactly one constant.

### Adaptive Learning Questions

**Q12: How does your quiz generation adapt to user mastery?**

> Three mechanisms work together: (1) **Adaptive difficulty**: We read the user's proficiency
> score (0.0-1.0) from PostgreSQL. High mastery (>0.7) increases difficulty by 2 levels
> and switches to application/synthesis questions. Low mastery (<0.3) decreases difficulty
> and focuses on recall. (2) **Dynamic few-shot**: We inject the user's liked/saved
> questions as few-shot examples in the MCQ prompt, so generated questions match their
> preferred style. (3) **Semantic deduplication**: Before serving a generated question,
> we check embedding cosine similarity against existing questions (threshold 0.85). If
> it's a paraphrase of an existing question, we auto-regenerate.

**Q13: How does semantic deduplication work?**

> Two-phase approach. Phase 1: exact text match (case-insensitive string comparison).
> Phase 2: embedding cosine similarity. We batch-embed the new question plus up to 20
> existing questions for the same concept, then compute dot products. If any similarity
> exceeds 0.85, it's flagged as duplicate. The threshold 0.85 empirically catches
> "What is X?" vs "Define X" while allowing "What is X?" vs "How does X relate to Y?".
> On duplicate detection, we regenerate once without few-shot examples to maximize variation.

### Architecture Questions

**Q14: How do you handle document chunking and why hierarchical?**

> We use a parent-child chunking strategy: documents are split into parent chunks (1000
> tokens) then each parent is split into children (250 tokens). Children are embedded
> (768-dim via MRL) for vector search (small = precise matches), but we return the parent
> context to the LLM (large = enough context). This balances retrieval precision with
> generation context. We use LangChain's `RecursiveCharacterTextSplitter` for both levels.

**Q15: How does your concept extraction maintain quality?**

> Three mechanisms: (1) Context-aware extraction - we fetch existing concept names and
> include them in the prompt so the LLM recognizes existing concepts and identifies
> relationships. (2) Synthesis agent - a two-phase deduplication process using embedding
> similarity pre-filtering followed by LLM analysis for candidate matches. (3) Human-in-
> the-loop - when conflicts are detected, the user makes the final decision.

**Q16: Explain your authentication flow.**

> Google OAuth 2.0 with no custom JWT. Frontend uses `@react-oauth/google` for sign-in,
> gets a Google ID token. Backend verifies the token with Google's API (`google.oauth2.
> id_token.verify_oauth2_token`). On first login, creates a user in PostgreSQL. The Google
> ID token itself serves as the session token (no custom JWT minting). The middleware
> `get_current_user()` verifies this token on every request.

**Q17: How do you handle streaming in chat?**

> SSE (Server-Sent Events) via FastAPI's `StreamingResponse`. We use LangGraph's
> `astream_events(state, config, version="v2")` to stream LLM token generation in
> real-time. Events are filtered by tags - the `generate_response_node` adds a
> `"final_response"` tag so we only stream tokens from the actual response, not from
> intermediate LLM calls like query analysis.

### System Design Questions

**Q18: What would you change if this needed to scale to 100K users?**

> 1. Replace MemorySaver with Redis-backed checkpointing for faster access
> 2. Add a task queue (Celery/Bull) for ingestion instead of in-process async
> 3. Shard Neo4j by user_id range (each shard handles N users)
> 4. Move from Supabase to dedicated PostgreSQL with read replicas
> 5. Add a caching layer (Redis) for frequently accessed concepts and feed items
> 6. Separate the LangGraph workers from the API server (LangGraph Platform)

**Q19: What are the main bottlenecks?**

> 1. LLM calls during ingestion (extraction + synthesis = 3-5 API calls per note)
> 2. Embedding generation for large documents (batch, but still slow for 50+ chunks)
> 3. Neo4j cold queries (first query per session has connection overhead)
> 4. Single-threaded Python for CPU-bound tasks (chunking, text processing)
> 5. Community summary generation (mitigated by caching + parallel LLM calls)

**Q20: How would you add a new graph to the system?**

> 1. Define a new state in `agents/states.py` (TypedDict, total=False)
> 2. Create `graphs/new_graph.py` with nodes, edges, routing
> 3. Add a wrapper in `supervisor_graph.py` if it should be supervisor-routed
> 4. Register in `langgraph.json` for LangGraph Platform
> 5. Add a public interface function (`run_new_workflow()`)
> 6. Create a FastAPI router endpoint that calls the public interface

### LangGraph Pattern Questions

**Q21: What LangGraph patterns does your project demonstrate? List them.**

> 1. **Supervisor/Orchestrator** (supervisor_graph): Central router with Command-based routing to subgraphs
> 2. **Human-in-the-Loop** (ingestion_graph): `interrupt()` + `Command(resume=...)` for concept review
> 3. **Self-Correction/Reflection** (mermaid_graph): Generate -> Validate -> Fix loop with max retries
> 4. **ReAct Agent** (research_graph): `create_react_agent` prebuilt with tool calling loop
> 5. **Parallel Fan-Out / Fan-In** (content_graph): Plan -> [MCQ, Flashcard, Diagram] -> Aggregate
> 6. **Conditional Routing** (ingestion_graph, quiz_graph): State-based branching with routing functions
> 7. **MessagesState** (chat_graph): `add_messages` reducer for conversation history
> 8. **Checkpointed Conversations** (chat_graph): PostgresSaver for multi-turn persistence
> 9. **Subgraph Composition** (supervisor_graph, content_graph): Graphs calling other graphs

**Q22: How do you handle the LangGraph Platform vs local execution difference?**

> We detect the environment with `"langgraph_api" in sys.modules`. In LangGraph Platform
> (Studio/Cloud), it provides its own checkpointer, so we compile without one. In local
> dev/production, we provide our own (MemorySaver or AsyncPostgresSaver). This is in every
> graph's `create_*_graph()` function.

**Q23: What is `total=False` on your TypedDict states and why is it important?**

> `total=False` means ALL fields are optional. This is critical because LangGraph nodes
> return PARTIAL state updates. If a node only updates `extracted_concepts`, it returns
> `{"extracted_concepts": [...]}` and all other fields remain unchanged. Without
> `total=False`, TypedDict would require every field in every return value, making
> partial updates impossible. This is a core LangGraph pattern - nodes are pure functions
> that return only what they change.

**Q24: Explain the difference between `add_conditional_edges` and `Command(goto=...)`. When would you use each?**

> `add_conditional_edges` defines routing as a separate function that's evaluated AFTER
> a node completes. The node returns state, then the routing function inspects state and
> returns the next node name. `Command(goto=...)` is returned FROM WITHIN the node itself,
> combining state updates and routing in one return. Use `Command` when the routing logic
> is tightly coupled to the node's business logic (like the supervisor's classify step).
> Use conditional edges when the routing is a separate concern (like the ingestion graph's
> overlap check, which is a simple threshold comparison).

### Production & Design Questions

**Q25: How do you ensure data isolation in a multi-tenant system?**

> Every Neo4j query includes `WHERE c.user_id = $user_id`. Every PostgreSQL query includes
> `WHERE user_id = :user_id`. This is enforced at the database client level, not at the
> application level. Additionally, the `get_current_user()` dependency extracts user_id
> from the Google OAuth token, so it's impossible to forge. The resume_ingestion function
> also verifies ownership by checking `state.values.get("user_id") != user_id` before
> allowing resumption.

**Q26: What are the failure modes and how do you handle them?**

> 1. **LLM call fails**: Every node has try/except that returns partial state with error field
> 2. **Neo4j unavailable**: Extraction continues without context (degrades gracefully)
> 3. **Embedding fails**: Chunks saved without embeddings (search degrades to keyword)
> 4. **HITL timeout**: Checkpointed state persists indefinitely, user can resume later
> 5. **Infinite loops**: Mermaid graph caps at 3 attempts; ReAct agent has built-in limits
> 6. **Duplicate content**: Content hash deduplication before ingestion starts
> 7. **Duplicate quizzes**: Semantic embedding similarity check prevents paraphrased duplicates

**Q27: Walk me through the complete lifecycle of a note from upload to quiz generation.**

> 1. **Frontend** calls `POST /api/v2/ingest` with markdown content
> 2. **Router** hashes content for deduplication, calls `run_ingestion()`
> 3. **parse_node**: Parses Marker-preprocessed markdown (or plain text fallback)
> 4. **chunk_node**: BookChunker creates image-aware parent chunks (~1400 chars) and child chunks (~300 chars)
> 5. **extract_concepts_node**: Fetches existing concept names from Neo4j, then extracts structured concepts via ExtractionAgent
> 6. **store_note_node**: INSERT INTO notes (with content hash) before chunk persistence (FK-safe ordering)
> 7. **embed_node**: Batch embeds all child chunks via Gemini embedding-001 (768 dims MRL)
> 8. **save_chunks_node**: INSERT INTO chunks with `cast(:embedding as vector)` for pgvector storage
> 9. **find_related_node**: Word-overlap matching against existing Neo4j concepts
> 10. **route_after_find_related**: Routes to synthesis (manual/default) or direct creation (auto path)
> 11. **synthesize_node**: SynthesisAgent compares new vs existing, recommends MERGE/SKIP/CREATE
> 12. **user_review_node**: `interrupt()` pauses, frontend shows review UI
> 13. User approves -> `Command(resume=...)` resumes graph
> 14. **create_concepts_node**: Neo4j upsert with normalized-name dedup + relationships (RELATED_TO, PREREQUISITE_OF, SUBTOPIC_OF) + NoteSource `EXPLAINS`
> 15. **link_synthesis_node**: Creates cross-reference edges between new and existing concepts
> 16. **generate_flashcards_node**: LLM generates cloze deletion cards, INSERT INTO flashcards
> 17. **generate_quiz_node**: ContentGeneratorAgent generates MCQs (2 per concept, adaptive difficulty, few-shot prompting), INSERT INTO quizzes
> 18. **Return**: note_id, concept_ids, term_card_ids, quiz_ids, processing_metadata
> 19. **Background**: ScannerAgent fires lazy quiz scan for any missed content

**Q28: What would you do differently if starting from scratch?**

> 1. Use LangGraph's `Send()` primitive for the content graph fan-out instead of multiple edges
> 2. Implement FSRS v5 instead of SM-2 (better mathematical foundation)
> 3. Use Neo4j vector index for hybrid search instead of pgvector (single-database retrieval)
> 4. Add structured output validation at EVERY LLM call (we have some manual JSON parsing)
> 5. Use LangGraph's Store for cross-thread user preferences instead of PostgreSQL settings
> 6. Implement proper error boundaries with retry decorators (tenacity) at the node level
> 7. Add a proper evaluation framework (LangSmith datasets) for measuring extraction quality
> 8. Use HNSW index instead of IVFFlat for pgvector (better recall at scale, no training needed)

---

## Appendix: Quick Reference Card

### LangGraph Patterns Cheat Sheet (from this project)

```
Pattern              | Graph           | Key Code
---------------------+-----------------+------------------------------------------
StateGraph           | ALL             | builder = StateGraph(MyState)
TypedDict state      | ALL             | class MyState(TypedDict, total=False)
add_messages reducer | chat, research  | messages: Annotated[list, add_messages]
Conditional edges    | ingestion, quiz | builder.add_conditional_edges(node, fn, map)
Command routing      | supervisor      | return Command(goto="node_name")
interrupt()          | ingestion       | user_response = interrupt({...})
Command(resume=...)  | ingestion       | graph.ainvoke(Command(resume=val), config)
Checkpointing        | chat, ingestion | builder.compile(checkpointer=checkpointer)
create_react_agent   | research        | create_react_agent(model, tools)
@tool decorator      | chat, research  | @tool async def my_tool(query: str) -> str
with_structured_out  | chat, ingestion | llm.with_structured_output(PydanticModel)
Fan-out/Fan-in       | content         | Multiple edges from plan -> [A,B,C] -> aggregate
Self-correction loop | mermaid         | validate -> fix -> validate (with max retries)
Subgraph composition | supervisor      | Wrapper functions map between state schemas
aget_state()         | chat            | Read state without re-running the graph
astream_events()     | chat (SSE)      | Stream LLM tokens with event filtering
```

### Model Choices Reference

```
Purpose                  | Model                        | Rationale
-------------------------+------------------------------+-------------------------------------------
Primary LLM              | gemini-2.5-flash             | Best cost/intelligence ($0.15/$0.60 per 1M)
Reasoning                | gemini-2.5-flash             | Built-in thinking, no separate model needed
Embeddings               | gemini-embedding-001         | #1 on MTEB, MRL-trained
Embedding Dims           | 768 (via MRL)                | 99.74% quality, 75% less storage
Web Search               | Tavily                       | AI-native, clean structured results
```

### Hybrid Retrieval Reference

```
Strategy       | Source     | Scoring         | Strength
---------------+------------+-----------------+----------------------------------------
Vector Search  | pgvector   | Cosine sim 0-1  | Semantic meaning ("ML" matches "machine learning")
Keyword Search | PostgreSQL | Fixed 0.5       | Exact terms ("ACID", "REST")
Graph Search   | Neo4j      | Seeds 0.7/0.4   | Structural relationships (prerequisites, subtopics)
Fusion         | RRF (K=60) | Rank-based      | Scale-invariant, no parameter tuning
```

### Key File Quick Reference

```
Need to understand...    | Read this file
-------------------------+------------------------------------------
ALL state definitions    | backend/agents/states.py
How graphs connect       | backend/graphs/supervisor_graph.py
HITL implementation      | backend/graphs/ingestion_graph.py (user_review_node)
GraphRAG retrieval       | backend/services/retrieval_service.py
Chat RAG pipeline        | backend/graphs/chat_graph.py (get_context_node)
Neo4j schema + queries   | backend/db/neo4j_client.py
PostgreSQL schema        | backend/db/init.sql
LLM/Embedding config     | backend/config/llm.py
Concept extraction       | backend/agents/extraction.py
MCQ generation           | backend/agents/content_generator.py (generate_mcq)
Feed + adaptive learning | backend/services/feed_service.py
Hybrid search            | backend/services/retrieval_service.py
Community detection      | backend/services/community_service.py
API endpoints            | backend/routers/*.py
```

---

*This guide covers every component of GraphRecall from an interview perspective. Each section
is designed to be independently readable - you can jump to any section and understand the
full context. The key is to be able to trace any user action from HTTP request through
LangGraph workflow to database operation and back.*
