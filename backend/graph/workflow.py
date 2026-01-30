"""LangGraph workflow definition for note ingestion."""

from datetime import datetime, timezone
from typing import Literal

import structlog
from langgraph.graph import END, StateGraph

from backend.graph.state import GraphState

logger = structlog.get_logger()


# ============================================================================
# Node Functions
# ============================================================================


async def parse_input_node(state: GraphState) -> GraphState:
    """
    Node 1: Parse and validate input content.

    Validates the input markdown/text and prepares it for extraction.
    Routes to error_node if input is invalid.
    """
    logger.info("parse_input_node: Processing input", user_id=state["user_id"])

    try:
        content = state.get("input_content", "")

        if not content or not content.strip():
            return {
                **state,
                "error_message": "Input content is empty or whitespace only",
            }

        # Clean and normalize the content
        cleaned_content = content.strip()

        # Basic validation - ensure content has substance
        if len(cleaned_content) < 10:
            return {
                **state,
                "error_message": "Input content is too short (minimum 10 characters)",
            }

        logger.info(
            "parse_input_node: Input validated",
            content_length=len(cleaned_content),
        )

        return {
            **state,
            "input_content": cleaned_content,
        }

    except Exception as e:
        logger.error("parse_input_node: Error parsing input", error=str(e))
        return {
            **state,
            "error_message": f"Failed to parse input: {str(e)}",
        }


async def extract_concepts_node(state: GraphState) -> GraphState:
    """
    Node 2: Extract concepts using Agent 1 (Extraction Agent).

    Uses GPT-3.5-turbo to identify concepts, definitions, and relationships
    from the input content.
    """
    from backend.agents.extraction import ExtractionAgent

    logger.info("extract_concepts_node: Starting extraction")

    try:
        agent = ExtractionAgent()
        result = await agent.extract(state["input_content"])

        # Convert ConceptCreate to Concept objects
        concepts = [
            {
                "id": f"concept-{i}-{hash(c.name) % 10000}",
                "name": c.name,
                "definition": c.definition,
                "domain": c.domain,
                "complexity_score": c.complexity_score,
                "confidence": c.confidence,
                "related_concepts": c.related_concepts,
                "prerequisites": c.prerequisites,
            }
            for i, c in enumerate(result.concepts)
        ]

        logger.info(
            "extract_concepts_node: Extraction complete",
            num_concepts=len(concepts),
        )

        return {
            **state,
            "extracted_concepts": concepts,
        }

    except Exception as e:
        logger.error("extract_concepts_node: Extraction failed", error=str(e))
        return {
            **state,
            "error_message": f"Concept extraction failed: {str(e)}",
        }


async def check_conflicts_node(state: GraphState) -> GraphState:
    """
    Node 3: Check for conflicts using Agent 2 (Synthesis Agent).

    Compares extracted concepts against existing knowledge graph
    to detect duplicates, conflicts, and enhancement opportunities.
    """
    from backend.agents.synthesis import SynthesisAgent

    logger.info(
        "check_conflicts_node: Checking conflicts",
        num_concepts=len(state.get("extracted_concepts", [])),
    )

    try:
        agent = SynthesisAgent()
        result = await agent.analyze(state["extracted_concepts"])

        logger.info(
            "check_conflicts_node: Analysis complete",
            num_decisions=len(result.decisions),
        )

        return {
            **state,
            "conflicts": [c.model_dump() for c in result.decisions],
        }

    except Exception as e:
        logger.error("check_conflicts_node: Conflict check failed", error=str(e))
        # Non-fatal: continue with empty conflicts
        return {
            **state,
            "conflicts": [],
        }


async def update_graph_node(state: GraphState) -> GraphState:
    """
    Node 4: Update the knowledge graph using Agent 3 (Graph Builder).

    Creates/updates concepts and relationships in Neo4j based on
    the extraction results and conflict analysis.
    """
    from backend.agents.graph_builder import GraphBuilderAgent

    logger.info("update_graph_node: Building graph updates")

    try:
        agent = GraphBuilderAgent()
        result = await agent.build(
            concepts=state["extracted_concepts"],
            conflicts=state.get("conflicts", []),
            note_id=state.get("note_id"),
        )

        logger.info(
            "update_graph_node: Graph updated",
            concepts_created=result["concepts_created"],
            relationships_created=result["relationships_created"],
        )

        return {
            **state,
            "concepts_created": result["concepts_created"],
            "relationships_created": result["relationships_created"],
            "processing_completed": datetime.now(timezone.utc),
            "final_output": f"Successfully processed note. Created {result['concepts_created']} concepts and {result['relationships_created']} relationships.",
        }

    except Exception as e:
        logger.error("update_graph_node: Graph update failed", error=str(e))
        return {
            **state,
            "error_message": f"Graph update failed: {str(e)}",
        }


async def error_node(state: GraphState) -> GraphState:
    """
    Error handler node.

    Centralizes error handling and ensures proper state cleanup.
    """
    logger.error(
        "error_node: Processing error",
        error=state.get("error_message", "Unknown error"),
    )

    return {
        **state,
        "processing_completed": datetime.now(timezone.utc),
        "final_output": f"Error: {state.get('error_message', 'Unknown error')}",
    }


# ============================================================================
# Routing Functions
# ============================================================================


def should_continue_after_parse(state: GraphState) -> Literal["extract", "error"]:
    """Route after parse_input: continue to extraction or handle error."""
    if state.get("error_message"):
        return "error"
    return "extract"


def should_continue_after_extract(state: GraphState) -> Literal["conflicts", "error"]:
    """Route after extraction: continue to conflict check or handle error."""
    if state.get("error_message"):
        return "error"
    if not state.get("extracted_concepts"):
        # No concepts extracted - this is an error
        return "error"
    return "conflicts"


def should_continue_after_conflicts(state: GraphState) -> Literal["update", "error"]:
    """Route after conflict check: continue to graph update or handle error."""
    if state.get("error_message"):
        return "error"
    return "update"


# ============================================================================
# Workflow Builder
# ============================================================================


def create_ingestion_workflow() -> StateGraph:
    """
    Create the LangGraph workflow for note ingestion.

    The workflow follows this flow:
    1. parse_input → validate and clean input
    2. extract_concepts → use Agent 1 to extract concepts
    3. check_conflicts → use Agent 2 to detect duplicates/conflicts
    4. update_graph → use Agent 3 to update Neo4j
    5. END or error_node

    Returns:
        A compiled StateGraph ready for execution
    """
    # Create the graph
    workflow = StateGraph(GraphState)

    # Add nodes
    workflow.add_node("parse_input", parse_input_node)
    workflow.add_node("extract_concepts", extract_concepts_node)
    workflow.add_node("check_conflicts", check_conflicts_node)
    workflow.add_node("update_graph", update_graph_node)
    workflow.add_node("error", error_node)

    # Set entry point
    workflow.set_entry_point("parse_input")

    # Add conditional edges
    workflow.add_conditional_edges(
        "parse_input",
        should_continue_after_parse,
        {
            "extract": "extract_concepts",
            "error": "error",
        },
    )

    workflow.add_conditional_edges(
        "extract_concepts",
        should_continue_after_extract,
        {
            "conflicts": "check_conflicts",
            "error": "error",
        },
    )

    workflow.add_conditional_edges(
        "check_conflicts",
        should_continue_after_conflicts,
        {
            "update": "update_graph",
            "error": "error",
        },
    )

    # Terminal edges
    workflow.add_edge("update_graph", END)
    workflow.add_edge("error", END)

    return workflow


# Create a compiled workflow instance
ingestion_graph = create_ingestion_workflow().compile()


async def run_ingestion_pipeline(
    user_id: str,
    content: str,
    note_id: str | None = None,
) -> dict:
    """
    Run the complete ingestion pipeline.

    Args:
        user_id: The user ID for this operation
        content: The raw input content (markdown/text)
        note_id: Optional note ID if already created

    Returns:
        The final state after pipeline completion
    """
    from backend.graph.state import create_initial_state

    initial_state = create_initial_state(user_id=user_id, content=content)
    if note_id:
        initial_state["note_id"] = note_id

    logger.info(
        "run_ingestion_pipeline: Starting",
        user_id=user_id,
        content_length=len(content),
    )

    # Run the workflow
    final_state = await ingestion_graph.ainvoke(initial_state)

    logger.info(
        "run_ingestion_pipeline: Complete",
        concepts_created=final_state.get("concepts_created", 0),
        error=final_state.get("error_message"),
    )

    return final_state
