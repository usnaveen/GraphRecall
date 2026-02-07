"""
LangGraph Supervisor Workflow

Orchestrates the entire system by routing requests to specialized subgraphs.
Demonstrates the Supervisor Pattern and Subgraph Composition.

Flow:
START → classify_request → (conditional)
    → [ingest] → ingestion_subgraph → END
    → [chat] → chat_subgraph → END
    → [research] → research_subgraph → END
    → [mermaid] → mermaid_subgraph → END
    → [content] → content_subgraph → END
"""

import structlog
from typing import Literal, Dict, Any
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from backend.agents.states import SupervisorState

# Import subgraphs
from backend.graphs.ingestion_graph import ingestion_graph
from backend.graphs.chat_graph import chat_graph
from backend.graphs.research_graph import research_agent as research_graph # Renamed for clarity
from backend.graphs.mermaid_graph import mermaid_graph
from backend.graphs.content_graph import content_graph
from backend.graphs.mcp_graph import mcp_graph

logger = structlog.get_logger()


# ============================================================================
# Node Functions
# ============================================================================


def classify_request_node(state: SupervisorState) -> Command:
    """
    Node 1: Classify request and route to subgraph.
    
    In a more advanced version, this would use an LLM router.
    For now, it uses the explicit `request_type`.
    """
    req_type = state.get("request_type", "unknown")
    payload = state.get("payload", {})
    user_id = state.get("user_id", "default_user")
    
    logger.info("classify_request_node: Routing", type=req_type)
    
    # Validation
    if req_type not in ["ingest", "chat", "research", "mermaid", "content", "verify"]:
        return Command(
            goto=END,
            update={"error": f"Unknown request type: {req_type}"}
        )
    
    # Map input state for subgraphs
    # Each subgraph needs specific inputs. We map the payload + headers.
    
    if req_type == "ingest":
        # Ingestion requires: content, user_id, etc.
        input_state = {
            "user_id": user_id,
            "raw_content": payload.get("content"),
            "title": payload.get("title"),
            "skip_review": payload.get("skip_review", False)
        }
        return Command(goto="ingest", update={"payload": payload}) # Just passing through for now, actually need to Invoke
        
    # NOTE: In LangGraph, to route to a node, we return Command(goto="node_name").
    # The node itself will be the compiled subgraph (see below).
    
    return Command(goto=req_type)


# ============================================================================
# Subgraph Wrappers (Input/Output Mapping)
# ============================================================================

# We need wrapper nodes to align state schemas between Supervisor and Subgraphs
# SupervisorState (payload) -> SubgraphState -> SupervisorState (result)

async def call_ingestion_subgraph(state: SupervisorState) -> dict:
    payload = state.get("payload", {})
    input_state = {
        "user_id": state.get("user_id"),
        "raw_content": payload.get("content"),
        "title": payload.get("title"),
        "skip_review": payload.get("skip_review", False)
    }
    
    # Invoke subgraph
    result = await ingestion_graph.ainvoke(input_state)
    
    return {
        "result": {
            "status": result.get("status"), 
            "note_id": result.get("note_id"),
            "concepts": len(result.get("created_concept_ids", []))
        }
    }

async def call_chat_subgraph(state: SupervisorState) -> dict:
    payload = state.get("payload", {})
    # Chat expects messages list or user message
    input_state = {
        "user_id": state.get("user_id"),
        "messages": [{"role": "user", "content": payload.get("message")}]
    }
    
    result = await chat_graph.ainvoke(input_state)
    last_message = result["messages"][-1]
    
    return {"result": {"response": last_message.content}}

async def call_research_subgraph(state: SupervisorState) -> dict:
    payload = state.get("payload", {})
    # Research expects message/input
    input_state = {
        "messages": [{"role": "user", "content": payload.get("topic")}]
    }
    
    result = await research_graph.ainvoke(input_state)
    last_message = result["messages"][-1]
    
    return {"result": {"summary": last_message.content}}

async def call_mermaid_subgraph(state: SupervisorState) -> dict:
    payload = state.get("payload", {})
    input_state = {
        "description": payload.get("description"),
        "chart_type": payload.get("chart_type", "flowchart")
    }
    
    result = await mermaid_graph.ainvoke(input_state)
    return {"result": result}

async def call_content_subgraph(state: SupervisorState) -> dict:
    payload = state.get("payload", {})
    input_state = {
        "topic": payload.get("topic"),
        "user_id": state.get("user_id")
    }
    
    result = await content_graph.ainvoke(input_state)
    return {"result": result.get("final_pack", {})}

async def call_verify_subgraph(state: SupervisorState) -> dict:
    payload = state.get("payload", {})
    input_state = {
        "claim": payload.get("claim")
    }
    
    result = await mcp_graph.ainvoke(input_state)
    return {"result": result}


# ============================================================================
# Graph Construction
# ============================================================================


def create_supervisor_graph():
    builder = StateGraph(SupervisorState)
    
    # 1. Router Node
    builder.add_node("classify", classify_request_node)
    
    # 2. Add Subgraph Nodes (Wrapped)
    # Instead of adding the graph directly, we add wrapper functions 
    # that map state in/out, acting as adapting layers.
    builder.add_node("ingest", call_ingestion_subgraph)
    builder.add_node("chat", call_chat_subgraph)
    builder.add_node("research", call_research_subgraph)
    builder.add_node("mermaid", call_mermaid_subgraph)
    builder.add_node("content", call_content_subgraph)
    builder.add_node("verify", call_verify_subgraph)
    
    # 3. Edges
    builder.add_edge(START, "classify")
    
    # The classify node uses Command(goto=...), so no explicit conditional edges needed
    # between classify and children if we trust the Command.
    # However, for clarity and visualization, we can define them or let Command handle it.
    # With Command, we don't strictly need add_conditional_edges, but explicit edges help.
    
    # All subgraphs go to END
    builder.add_edge("ingest", END)
    builder.add_edge("chat", END)
    builder.add_edge("research", END)
    builder.add_edge("mermaid", END)
    builder.add_edge("content", END)
    builder.add_edge("verify", END)
    
    return builder.compile()

supervisor_graph = create_supervisor_graph()
