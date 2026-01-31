"""
LangGraph State Definitions for GraphRecall Workflows

This module defines typed state schemas for LangGraph workflows using TypedDict.
Following LangGraph 1.0.7 best practices:
- Explicit state schemas with TypedDict
- Pure node functions that return partial state updates
- Minimal, typed state objects
"""

from typing import Optional
from typing_extensions import TypedDict


class IngestionState(TypedDict, total=False):
    """
    State for the note ingestion workflow.
    
    This state flows through the ingestion graph with conditional edges:
    START -> extract_concepts -> store_note -> find_related 
          -> (conditional) -> [synthesize -> user_review] OR [create_concepts]
          -> link_synthesis -> generate_flashcards -> END
    
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
    
    # Processing fields (updated by nodes)
    note_id: Optional[str]
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
    flashcard_ids: list[str]        # Generated flashcard IDs
    
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
    State for the GraphRAG chat workflow.
    
    Used for knowledge-aware conversation with graph traversal.
    """
    user_id: str
    query: str
    conversation_history: list[dict]  # [{role, content}]
    
    # Analysis
    query_intent: str
    extracted_entities: list[str]
    
    # Context retrieval
    graph_context: dict
    rag_context: list[dict]
    
    # Response
    response: str
    sources: list[str]
    related_concepts: list[str]
