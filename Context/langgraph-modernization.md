## Branch: `refactor/langgraph-modernization`

## Overview

Comprehensive refactoring to upgrade GraphRecall from pre-1.0 LangGraph patterns to modern LangGraph 1.0+ architecture. Removes V1 dead code, builds new StateGraphs for chat and research, adds supervisor orchestration, fixes fake streaming, and integrates LangSmith + Context7 MCP.
* * *

## Phase 1: Foundation -- Deps, V1 Removal, `/api/ingest` Migration (Day 1-2)

### 1A. Create branch and update dependencies

**File: `pyproject.toml`** -- Update LangGraph from `>=0.0.40` to `>=1.0.0`
    
    
    "langgraph>=1.0.0",
    "langgraph-checkpoint-postgres>=2.0.0",
    "langchain>=0.3.0",
    "langchain-openai>=0.2.0",
    "langchain-community>=0.3.0",
    "langsmith>=0.2.0",

Run `uv lock && uv sync` to validate resolution.

### 1B. Remove V1 graph entirely

**DELETE these files:**

- `backend/graph/workflow.py`
- `backend/graph/state.py`
- `backend/graph/__init__.py`
- Remove `backend/graph/` directory

### 1C. Rewire main.py -- Migrate `/api/ingest` to V2

**File: `backend/main.py`**

- Line 23: Replace `from backend.graph.workflow import run_ingestion_pipeline` with `from backend.graphs.ingestion_graph import run_ingestion`
- Lines 138-222: Rewrite `POST /api/ingest` handler to call `run_ingestion(content=..., user_id=..., note_id=..., skip_review=True)` -- The V1 endpoint auto-approved, so we use `skip_review=True` to maintain behavior
- Map V2 response shape (`concept_ids`, `flashcard_ids`, `status`) to V1's `IngestResponse` model

### 1D. Rewire review.py -- Remove V1 import

**File: `backend/routers/review.py`**

- Line 17: Replace `from backend.graph.workflow import run_ingestion_pipeline` with `from backend.graphs.ingestion_graph import run_ingestion`
- Line 81: Replace `run_ingestion_pipeline(...)` call with `run_ingestion(content=..., user_id=..., note_id=..., skip_review=True)`
- Lines 96-129 (ExtractionAgent/SynthesisAgent direct calls): **Keep as-is** -- these are used for the non-skip review path and work independently of the graph

### 1E. Fix integration tests

**File: `backend/tests/test_integration.py`**

- Lines 8-15: Replace all V1 imports with V2 equivalents
- Rewrite `TestIngestionPipeline` to test V2 nodes from `backend.graphs.ingestion_graph`
- Tests should use `MemorySaver` checkpointer and mock DB clients
* * *

## Phase 2: Modernize HITL -- `interrupt()` + Fix Streaming (Day 2-3)

### 2A. Replace `interrupt_before` with `interrupt()` function

**File: `backend/graphs/ingestion_graph.py`**

Add import: `from langgraph.types import interrupt, Command`

Rewrite `user_review_node` (line 291):

- If `skip_review=True`: auto-approve all, return partial state
- Otherwise: call `interrupt({"synthesis_decisions": ..., "extracted_concepts": ...})` which pauses the graph
- The return value of `interrupt()` is what the caller provides when resuming with `Command(resume=...)`

Remove the dual-graph pattern: Delete `ingestion_graph_auto` (line 676). One graph handles both skip/non-skip via the state flag.

Update `create_ingestion_graph()` (line 603): Remove `enable_interrupts` parameter. Always compile the same graph:

python
    
    
    def create_ingestion_graph():
        builder = StateGraph(IngestionState)
        # ... nodes and edges ...
        return builder.compile(checkpointer=get_checkpointer())

### 2B. Update resume to use `Command`

**File: `backend/graphs/ingestion_graph.py`**

Rewrite `resume_ingestion()` (line 779):

python
    
    
    async def resume_ingestion(thread_id, user_approved_concepts=None, user_cancelled=False):
        config = {"configurable": {"thread_id": thread_id}}
        resume_value = {"approved_concepts": user_approved_concepts or [], "cancelled": user_cancelled}
        result = await ingestion_graph.ainvoke(Command(resume=resume_value), config)
        ...

### 2C. Fix fake streaming

**File: `backend/agents/graphrag_chat.py`**

- Factor out prompt building from `generate_response()` into `_build_prompt()` (reusable)
- Add `stream_response()` async generator method that calls `self.llm.astream(prompt)`

**File: `backend/routers/chat.py`** -- Lines 648-693
- Rewrite `/api/chat/stream` to: run analysis + context retrieval first (fast), then stream LLM tokens via `chat_agent.stream_response()` yielding real SSE chunks
* * *

## Phase 3: Build Chat StateGraph (Day 4-5)

### 3A. Enhance ChatState

**File: `backend/agents/states.py`**

Expand `ChatState` (line 83) with proper typed fields:

python
    
    
    class ChatState(TypedDict, total=False):
        user_id: str
        query: str
        conversation_history: list[dict]
    
        # Analysis
        query_intent: str
        extracted_entities: list[str]
        requires_graph: bool
        requires_rag: bool
    
        # Context
        graph_context: dict
        rag_context: list[dict]
    
        # Output
        response: str
        sources: list[dict]
        related_concepts: list[dict]
        suggested_actions: list[str]
        error: Optional[str]
    ```
    
    ### 3B. Create ChatGraph
    
    **NEW FILE: `backend/graphs/chat_graph.py`**
    
    Decompose `GraphRAGAgent.chat()` into a StateGraph:
    ```
    START → analyze_query → route_context → get_graph_context → get_rag_context → generate_response → END

- `analyze_query_node`: Calls `GraphRAGAgent.analyze_query()`, sets intent/entities/flags
- `route_context_node`: Uses `Command(goto=[...])` to dynamically route to graph/rag/both
- `get_graph_context_node`: Calls `GraphRAGAgent.get_graph_context()`
- `get_rag_context_node`: Calls `GraphRAGAgent.get_rag_context()`
- `generate_response_node`: Calls `GraphRAGAgent.generate_response()`, sets response + metadata

The `GraphRAGAgent` class remains as a utility -- its methods are called by nodes. The agent doesn't become a node itself.

### 3C. Wire into chat router

**File: `backend/routers/chat.py`**

- `POST /api/chat`: Use `run_chat()` from chat_graph instead of direct `GraphRAGAgent.chat()`
- `POST /api/chat/stream`: Use `chat_graph.astream_events()` for real graph-level streaming
- Keep `/api/chat/quick` as a simpler wrapper
* * *

## Phase 4: Build Research StateGraph (Day 5-6)

### 4A. Add ResearchState

**File: `backend/agents/states.py`**

python
    
    
    class ResearchState(TypedDict, total=False):
        user_id: str
        topic: str
        force: bool
        is_sufficient: bool
        existing_resources: list[dict]
        search_results: list[dict]
        summary: str
        key_points: list[str]
        note_content: str
        sources: list[dict]
        note_id: Optional[str]
        status: str
        error: Optional[str]
    ```
    
    ### 4B. Create ResearchGraph
    
    **NEW FILE: `backend/graphs/research_graph.py`**
    
    Convert `WebResearchAgent.research_topic()` pipeline:
    ```
    START → check_resources → (sufficient? → END) / (→ search_web → synthesize → save_note → END)

`WebResearchAgent` methods called by graph nodes, same pattern as chat.

* * *

## Phase 5: Supervisor Graph + Subgraph Composition (Day 7-8)

### 5A. Add SupervisorState

**File: `backend/agents/states.py`**

python
    
    
    class SupervisorState(TypedDict, total=False):
        user_id: str
        request_type: str  # "ingest", "chat", "research"
        request_payload: dict
        result: dict
        error: Optional[str]
    ```
    
    ### 5B. Create Supervisor Graph
    
    **NEW FILE: `backend/graphs/supervisor_graph.py`**
    
    Orchestrator that routes between subgraphs:
    ```
    START → classify_request → (conditional) → [ingestion | chat | research] → collect_result → END

- `classify_request_node`: Rule-based routing on `request_type` (can be upgraded to LLM-based later)
- Each subgraph is composed using `builder.add_node("ingest", create_ingestion_graph())`
- State mapping between supervisor and subgraph states via input/output transformations

### 5C. Refactor graph factories

Each graph file must expose a `create_*_graph()` factory function returning a compiled graph, suitable for both standalone use and subgraph composition.

* * *

## Phase 6: Observability -- LangSmith + LangGraph Studio (Day 9-10)

### 6A. LangSmith integration

**File: `backend/main.py`** -- Add to lifespan:

python
    
    
    import os
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", "graphrecall")

No code changes needed -- LangGraph auto-instruments when env vars are set.

### 6B. LangGraph Studio config

**NEW FILE: `langgraph.json`** (project root)

json
    
    
    {
      "graphs": {
        "ingestion": "./backend/graphs/ingestion_graph.py:ingestion_graph",
        "chat": "./backend/graphs/chat_graph.py:chat_graph",
        "research": "./backend/graphs/research_graph.py:research_graph",
        "supervisor": "./backend/graphs/supervisor_graph.py:supervisor_graph"
      },
      "env": ".env"
    }

### 6C. Add LLM caching

**File: `backend/main.py`** -- In lifespan startup:

python
    
    
    from langchain_core.globals import set_llm_cache
    from langchain_community.cache import InMemoryCache
    set_llm_cache(InMemoryCache())
    ```
    
    ---
    
    ## Phase 7: Context7 MCP Integration (Day 10-11)
    
    ### 7A. Context7 verification agent
    
    **NEW FILE: `backend/agents/context7_verifier.py`**
    
    Agent that verifies extracted concept definitions against authoritative docs via Context7 MCP:
    - Query Context7 for each extracted concept's domain (e.g., "Machine Learning")
    - Compare extracted definition against authoritative source
    - Adjust confidence score and flag inaccuracies
    - Graceful no-op when `CONTEXT7_API_KEY` not configured
    
    ### 7B. Add verification node to ingestion graph
    
    **File: `backend/graphs/ingestion_graph.py`**
    
    Insert `verify_concepts_node` after `extract_concepts_node`:
    ```
    START → extract_concepts → verify_concepts → store_note → find_related → ...

Node skips silently if Context7 is unconfigured. Never blocks ingestion on verification failure.

* * *

## Phase 8: Testing (Day 12-13)

### 8A. Ingestion graph tests

**NEW FILE: `backend/tests/test_ingestion_graph.py`**

- Happy path (no overlap) → full pipeline to END
- Synthesis path (overlap detected) → interrupt → resume → END
- Cancel path → interrupt → resume with cancel → END
- Skip review path → bypasses interrupt entirely
- Error in extraction → graceful error handling

### 8B. Chat graph tests

**NEW FILE: `backend/tests/test_chat_graph.py`**

- Graph-only context query
- RAG-only context query
- Both contexts query
- Error fallback behavior

### 8C. Research graph tests

**NEW FILE: `backend/tests/test_research_graph.py`**

- Sufficient resources → early exit
- Insufficient → web search → synthesize → save
- Force research flag

### 8D. Supervisor graph tests

**NEW FILE: `backend/tests/test_supervisor.py`**

- Routes to correct subgraph based on request_type
- Handles unknown request_type gracefully

All tests use `MemorySaver`, mock DB clients, mock LLM responses.

* * *

## Phase 9: Cleanup + Polish (Day 13-14)

### 9A. Update exports

**File: `backend/graphs/__init__.py`** -- Add new graph exports:

python
    
    
    from backend.graphs.chat_graph import chat_graph, run_chat
    from backend.graphs.research_graph import research_graph, run_research
    from backend.graphs.supervisor_graph import supervisor_graph
    ```
    
    ### 9B. Dead code removal
    - Remove `backend/graph/` directory entirely (done in Phase 1)
    - Remove `ingestion_graph_auto` global (done in Phase 2)
    - Clean unused imports across modified files
    
    ### 9C. Add `.env.example`
    
    **NEW FILE: `.env.example`**
    ```
    DATABASE_URL=postgresql://graphrecall:password@localhost:5432/graphrecall
    NEO4J_URI=bolt://localhost:7687
    NEO4J_USER=neo4j
    NEO4J_PASSWORD=password
    OPENAI_API_KEY=sk-...
    LANGCHAIN_TRACING_V2=true
    LANGCHAIN_API_KEY=ls-...
    LANGCHAIN_PROJECT=graphrecall
    CONTEXT7_API_KEY=...
    ENVIRONMENT=development

* * *

## File Manifest

### DELETE (3 files)

| File | Reason | 
| ---- | ----  |
| `backend/graph/workflow.py` | V1 ingestion, replaced by V2 | 
| `backend/graph/state.py` | V1 state, replaced by `agents/states.py` | 
| `backend/graph/__init__.py` | V1 package init | 

### CREATE (10 files)

| File | Purpose | 
| ---- | ----  |
| `backend/graphs/chat_graph.py` | Chat StateGraph | 
| `backend/graphs/research_graph.py` | Research StateGraph | 
| `backend/graphs/supervisor_graph.py` | Supervisor orchestrator | 
| `backend/agents/context7_verifier.py` | Context7 MCP integration | 
| `backend/tests/test_ingestion_graph.py` | V2 ingestion tests | 
| `backend/tests/test_chat_graph.py` | Chat graph tests | 
| `backend/tests/test_research_graph.py` | Research graph tests | 
| `backend/tests/test_supervisor.py` | Supervisor tests | 
| `langgraph.json` | LangGraph Studio config | 
| `.env.example` | Environment template | 

### MODIFY (9 files)

| File | Changes | 
| ---- | ----  |
| `pyproject.toml` | Deps → LangGraph 1.0+ | 
| `backend/main.py` | Remove V1 import, wire V2, add LangSmith + caching | 
| `backend/routers/review.py` | Remove V1 import, wire V2 for skip_review path | 
| `backend/routers/chat.py` | Wire to ChatGraph, fix real streaming | 
| `backend/graphs/ingestion_graph.py` | `interrupt()` + `Command`, remove dual-graph, add verify node | 
| `backend/agents/states.py` | Enhance ChatState, add ResearchState + SupervisorState | 
| `backend/agents/graphrag_chat.py` | Add `_build_prompt()` + `stream_response()` | 
| `backend/graphs/__init__.py` | Export new graphs | 
| `backend/tests/test_integration.py` | Rewrite for V2 | 

* * *

## Verification

After each phase, validate:

1. **Phase 1**: `uv sync` succeeds, `pytest backend/tests/` passes, app starts with `uvicorn backend.main:app`
2. **Phase 2**: `POST /api/v2/ingest` with `skip_review=false` pauses correctly, resume works via `POST /api/v2/ingest/{thread_id}/approve`
3. **Phase 3**: `POST /api/chat` returns valid response via new ChatGraph
4. **Phase 4**: Research graph can be invoked standalone
5. **Phase 5**: Supervisor routes requests to correct subgraph
6. **Phase 6**: LangSmith traces appear in dashboard (requires API key)
7. **Phase 7**: Context7 verification runs when configured, no-ops when not
8. **Phase 8**: `pytest backend/tests/` -- all new tests pass
9. **Phase 9**: No unused imports, clean git diff, `.env.example` documented