"""
LangGraph State Definitions for GraphRecall Workflows

This module defines typed state schemas for LangGraph workflows using TypedDict.
Following LangGraph 1.0.7 best practices:
- Explicit state schemas with TypedDict
- Pure node functions that return partial state updates
- Minimal, typed state objects
"""

from typing import Annotated, Any, Dict, List, Optional, Union, Sequence, Literal
from typing_extensions import TypedDict


class IngestionState(TypedDict, total=False):
    """
    State for the note ingestion workflow.
    
    This state flows through the ingestion graph with conditional edges:
    START -> extract_concepts -> store_note -> find_related 
          -> (conditional) -> [synthesize -> user_review] OR [create_concepts]
          -> link_synthesis -> generate_term_cards -> END
    
    Following LangGraph best practices:
    - All fields are explicitly typed
    - `total=False` allows partial state updates from nodes
    - Each node returns only the fields it updates
    """
    # Input fields (set at invocation)
    user_id: str
    raw_content: str
    title: Optional[str]
    skip_review: bool  # If True, auto-approve concepts
    content_hash: Optional[str]  # Hash for deduplication
    resource_type: Optional[str]  # e.g. "book", "notes", "article"
    
    # Processing fields (updated by nodes)
    note_id: Optional[str]
    file_type: Optional[str]  # pdf, pptx, md, etc.
    parsed_document: Optional[dict]  # {markdown_content, images, metadata}
    chunks: list[dict]  # [{id, content, parent_id, ...}]
    propositions: list[dict] # Added for Phase 3
    
    extracted_concepts: list[dict]  # [{name, description, domain, ...}]
    related_concepts: list[dict]    # Existing concepts found via similarity
    
    # Overlap detection (for conditional routing)
    overlap_ratio: float  # 0.0 to 1.0
    needs_synthesis: bool
    
    # Synthesis decisions (for HITL review)
    synthesis_decisions: list[dict]  # [{new_concept, matches, recommended_action}]
    awaiting_user_approval: bool
    user_approved_concepts: list[dict]  # Concepts approved by user
    user_cancelled: bool
    
    # Synthesis completion
    synthesis_completed: bool
    
    # Output fields
    created_concept_ids: list[str]  # Neo4j concept IDs
    term_card_ids: list[str]        # Generated term card IDs
    quiz_ids: list[str]             # Generated quiz IDs

    # Processing metadata (geekout facts for UI)
    processing_metadata: dict  # Accumulated metadata from each node

    # Error handling
    error: Optional[str]


class ReviewSessionState(TypedDict, total=False):
    """
    State for the spaced repetition review workflow.
    
    This will be used for the review session graph (future implementation).
    """
    user_id: str
    session_id: Optional[str]
    
    # Cards to review
    due_cards: list[dict]
    current_card_index: int
    
    # User responses
    responses: list[dict]  # [{card_id, quality, response_time_ms}]
    
    # Session stats
    cards_reviewed: int
    correct_count: int
    session_completed: bool


class ChatState(TypedDict, total=False):
    """
    State for the GraphRAG chat workflow (LangGraph refactor).
    
    Uses MessagesState pattern with add_messages reducer for
    automatic message history management.
    
    Interview-ready patterns:
    - Annotated list with add_messages for message accumulation
    - Proper message types (SystemMessage, HumanMessage, AIMessage)
    """
    from typing import Annotated
    from langchain_core.messages import BaseMessage
    from langgraph.graph.message import add_messages
    
    # Core message history with add_messages reducer
    messages: Annotated[list[BaseMessage], add_messages]
    
    # User context
    user_id: str
    
    # Query analysis
    intent: str
    entities: list[str]
    
    # Context retrieval
    graph_context: dict
    rag_context: list[dict]
    
    # Response metadata
    sources: list[dict]
    related_concepts: list[dict]


class QuizState(TypedDict, total=False):
    """
    State for quiz generation workflow.
    
    Demonstrates conditional routing based on resource sufficiency.
    """
    # Input
    topic: str
    user_id: str
    num_questions: int
    
    # Resources
    resources: list[dict]
    resource_count: int
    
    # Routing decision
    needs_research: bool
    research_results: list[dict]
    payload: dict      # Input arguments for the subgraph
    result: dict       # Output from the subgraph
    error: Optional[str]


class MCPState(TypedDict, total=False):
    """
    State for the MCP (Model Context Protocol) Verification Graph.
    """
    # Input
    claim: str
    
    # Internal
    mcp_server_response: dict
    
    # Output
    verdict: Literal["verified", "incorrect", "ambiguous"]
    explanation: str
    sources: list[str]


class ResearchState(TypedDict, total=False):
    """
    State for research agent (ReAct pattern).
    
    Used with create_react_agent prebuilt.
    """
    from typing import Annotated
    from langchain_core.messages import BaseMessage
    from langgraph.graph.message import add_messages
    
    # Message history for ReAct loop
    messages: Annotated[list[BaseMessage], add_messages]
    
    # Research context
    topic: str
    user_id: str
    
class MermaidState(TypedDict, total=False):
    """
    State for Mermaid diagram generation (Self-Correction pattern).
    
    Flow: generate -> validate -> (invalid) -> fix -> validate ...
    """
    # Input
    description: str
    chart_type: str
    
    # Processing
    current_code: str
    validation_error: Optional[str]
    attempt_count: int
    
    # Output
    final_code: str
    explanation: str


class ContentState(TypedDict, total=False):
    """
    State for parallel content generation (Parallel/Map-Reduce pattern).
    
    Flow: plan -> [mcq, flashcards, diagram] -> aggregate
    """
    # Input
    topic: str
    user_id: str
    
    # Internal Resources
    concepts: list[dict]
    
    # Parallel Outputs
    mcqs: list[dict]
    term_cards: list[dict]
    diagram: dict  # {code, explanation}
    
    # Final Output
    final_pack: dict


class SupervisorState(TypedDict, total=False):
    """
    State for the Supervisor (Orchestrator) Graph.
    Methods: Classify -> Route -> Aggregate
    """
    # Input
    request_type: str # ingest | chat | research | mermaid | content | verify
    user_id: str
    payload: dict     # Original request payload
    
    # Internal
    next_node: str    # Routing decision
    
    # Output
    result: dict      # Result from subgraph
    error: Optional[str]

