"""LangGraph state definitions for GraphRecall workflows."""

from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from backend.models.schemas import (
    Concept,
    Conflict,
    GraphOperation,
)


class GraphState(TypedDict):
    """
    State object for the LangGraph ingestion workflow.

    This state is passed between nodes in the graph and accumulates
    information as the pipeline processes a note.
    """

    # =========================================================================
    # Input Fields
    # =========================================================================

    # User identification
    user_id: str

    # Action type for the workflow
    action: Literal["ingest", "query"]

    # Raw input content (markdown/text)
    input_content: Optional[str]

    # Note ID (assigned after PostgreSQL insert)
    note_id: Optional[str]

    # =========================================================================
    # Processing Fields
    # =========================================================================

    # Concepts extracted by Agent 1 (Extraction)
    extracted_concepts: Annotated[list[Concept], "Concepts found in the input"]

    # Conflicts detected by Agent 2 (Synthesis)
    conflicts: Annotated[list[Conflict], "Conflicts with existing knowledge"]

    # Graph operations to execute (from Agent 3)
    graph_updates: Annotated[list[GraphOperation], "Pending graph operations"]

    # =========================================================================
    # Output Fields
    # =========================================================================

    # Final output message/summary
    final_output: Optional[str]

    # Error message if pipeline fails
    error_message: Optional[str]

    # Processing metadata
    processing_started: Optional[datetime]
    processing_completed: Optional[datetime]

    # Statistics
    concepts_created: int
    relationships_created: int


class IngestionInput(BaseModel):
    """Input model for the ingestion workflow."""

    user_id: str = Field(
        default="00000000-0000-0000-0000-000000000001",
        description="User ID for the note",
    )
    content: str = Field(..., description="Markdown/text content to ingest")
    source_url: Optional[str] = Field(default=None)


class IngestionOutput(BaseModel):
    """Output model for the ingestion workflow."""

    note_id: str
    concepts_extracted: list[str]
    concepts_created: int
    relationships_created: int
    status: str
    error_message: Optional[str] = None
    processing_time_ms: Optional[float] = None


def create_initial_state(
    user_id: str,
    content: str,
    action: Literal["ingest", "query"] = "ingest",
) -> GraphState:
    """
    Create an initial state for the workflow.

    Args:
        user_id: The user ID for this operation
        content: The raw input content
        action: The type of action (ingest or query)

    Returns:
        A properly initialized GraphState
    """
    return GraphState(
        user_id=user_id,
        action=action,
        input_content=content,
        note_id=None,
        extracted_concepts=[],
        conflicts=[],
        graph_updates=[],
        final_output=None,
        error_message=None,
        processing_started=datetime.now(timezone.utc),
        processing_completed=None,
        concepts_created=0,
        relationships_created=0,
    )
