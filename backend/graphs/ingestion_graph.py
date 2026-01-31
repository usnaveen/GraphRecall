"""
LangGraph Ingestion Workflow (V2)

Upgraded architecture following Claude's LangGraph patterns:
1. Conditional edges for branching (overlap detection)
2. Human-in-the-loop with interrupt_before
3. PostgresSaver for production durability
4. Separate routing functions

Flow:
START → extract_concepts → store_note → find_related 
      → (conditional) → [needs_synthesis? → synthesize → user_review]
                       → [no_overlap → create_concepts → generate_flashcards → END]
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, Literal

import structlog
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

from backend.agents.states import IngestionState
from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.graphs.checkpointer import get_checkpointer

logger = structlog.get_logger()

# ============================================================================
# LLM Configuration
# ============================================================================

llm_extraction = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.2,
    model_kwargs={"response_format": {"type": "json_object"}},
)

llm_flashcard = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.3,
    model_kwargs={"response_format": {"type": "json_object"}},
)

# ============================================================================
# Node Functions
# ============================================================================


async def extract_concepts_node(state: IngestionState) -> dict:
    """
    Node 1: Extract concepts from raw content using LLM.
    
    Input: raw_content, title
    Output: extracted_concepts
    """
    logger.info(
        "extract_concepts_node: Starting",
        content_length=len(state.get("raw_content", "")),
    )
    
    prompt = f"""You are a concept extraction expert. Extract key concepts from this note.

Content:
{state.get("raw_content", "")[:4000]}

Instructions:
1. Focus on technical terms, theories, algorithms, or core ideas
2. Extract 3-7 concepts maximum
3. Each concept needs a name and brief description
4. Identify prerequisites and related concepts

Return ONLY valid JSON:
{{
    "concepts": [
        {{
            "name": "Concept Name",
            "definition": "Brief definition (1-2 sentences)",
            "domain": "Subject area like 'Machine Learning' or 'Biology'",
            "complexity_score": 5,
            "prerequisites": [],
            "related_concepts": []
        }}
    ]
}}
"""
    
    try:
        response = await llm_extraction.ainvoke(prompt)
        content = response.content.strip()
        
        # Handle markdown code blocks
        if content.startswith("```json"):
            content = content.split("```json")[1].split("```")[0].strip()
        elif content.startswith("```"):
            content = content.split("```")[1].split("```")[0].strip()
        
        data = json.loads(content)
        concepts = data.get("concepts", [])
        
        logger.info(
            "extract_concepts_node: Complete",
            num_concepts=len(concepts),
        )
        
        return {"extracted_concepts": concepts}
        
    except json.JSONDecodeError as e:
        logger.error("extract_concepts_node: JSON parse error", error=str(e))
        return {"extracted_concepts": [], "error": f"JSON parse error: {e}"}
    except Exception as e:
        logger.error("extract_concepts_node: Failed", error=str(e))
        return {"extracted_concepts": [], "error": str(e)}


async def store_note_node(state: IngestionState) -> dict:
    """
    Node 2: Store the note in PostgreSQL.
    
    Input: raw_content, title, user_id
    Output: note_id
    """
    note_id = state.get("note_id") or str(uuid.uuid4())
    user_id = state.get("user_id", "default_user")
    
    logger.info("store_note_node: Storing note", note_id=note_id)
    
    try:
        pg_client = await get_postgres_client()
        
        # Insert or update note
        await pg_client.execute(
            """
            INSERT INTO notes (id, user_id, title, content, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $5)
            ON CONFLICT (id) DO UPDATE SET
                content = $4,
                updated_at = $5
            """,
            uuid.UUID(note_id),
            user_id,
            state.get("title") or "Untitled Note",
            state.get("raw_content", ""),
            datetime.utcnow(),
        )
        
        logger.info("store_note_node: Complete", note_id=note_id)
        return {"note_id": note_id}
        
    except Exception as e:
        logger.error("store_note_node: Failed", error=str(e))
        return {"note_id": note_id, "error": str(e)}


async def find_related_node(state: IngestionState) -> dict:
    """
    Node 3: Find existing concepts related to the extracted ones.
    
    Input: extracted_concepts
    Output: related_concepts, needs_synthesis, overlap_ratio
    """
    logger.info("find_related_node: Starting")
    
    extracted = state.get("extracted_concepts", [])
    if not extracted:
        return {"related_concepts": [], "needs_synthesis": False, "overlap_ratio": 0.0}
    
    try:
        neo4j = await get_neo4j_client()
        
        # Get all existing concepts
        query = """
        MATCH (c:Concept)
        RETURN c.id AS id, c.name AS name, c.definition AS definition, 
               c.domain AS domain, c.complexity_score AS complexity_score
        LIMIT 100
        """
        
        existing = await neo4j.execute_query(query, {})
        
        if not existing:
            logger.info("find_related_node: No existing concepts")
            return {"related_concepts": [], "needs_synthesis": False, "overlap_ratio": 0.0}
        
        # Simple name matching for MVP
        # (Production would use embeddings/vector search)
        related = []
        extracted_names = [c.get("name", "").lower() for c in extracted]
        
        for concept in existing:
            name = concept.get("name", "").lower()
            for ext_name in extracted_names:
                # Check for significant overlap
                if ext_name in name or name in ext_name or _word_overlap(ext_name, name) > 0.5:
                    related.append(concept)
                    break
        
        # Calculate overlap ratio
        overlap_ratio = len(related) / len(extracted) if extracted else 0.0
        needs_synthesis = overlap_ratio > 0.3  # Threshold for synthesis
        
        logger.info(
            "find_related_node: Complete",
            num_related=len(related),
            overlap_ratio=overlap_ratio,
            needs_synthesis=needs_synthesis,
        )
        
        return {
            "related_concepts": related, 
            "needs_synthesis": needs_synthesis,
            "overlap_ratio": overlap_ratio,
        }
        
    except Exception as e:
        logger.error("find_related_node: Failed", error=str(e))
        return {"related_concepts": [], "needs_synthesis": False, "overlap_ratio": 0.0}


def _word_overlap(s1: str, s2: str) -> float:
    """Calculate word overlap between two strings."""
    words1 = set(s1.lower().split())
    words2 = set(s2.lower().split())
    if not words1 or not words2:
        return 0.0
    intersection = words1 & words2
    return len(intersection) / min(len(words1), len(words2))


async def synthesize_node(state: IngestionState) -> dict:
    """
    Node 4a: Synthesize new concepts with existing ones.
    
    This node is called when overlap is detected.
    Prepares synthesis data for user review.
    
    Input: extracted_concepts, related_concepts
    Output: synthesis_decisions (pending user approval)
    """
    logger.info("synthesize_node: Starting synthesis analysis")
    
    extracted = state.get("extracted_concepts", [])
    related = state.get("related_concepts", [])
    
    # Prepare synthesis decisions for user review
    synthesis_decisions = []
    
    for ext in extracted:
        ext_name = ext.get("name", "").lower()
        matches = []
        
        for rel in related:
            rel_name = rel.get("name", "").lower()
            if ext_name in rel_name or rel_name in ext_name or _word_overlap(ext_name, rel_name) > 0.5:
                matches.append({
                    "existing_id": rel.get("id"),
                    "existing_name": rel.get("name"),
                    "similarity": _word_overlap(ext_name, rel_name),
                })
        
        if matches:
            synthesis_decisions.append({
                "new_concept": ext,
                "matches": matches,
                "recommended_action": "merge" if matches[0].get("similarity", 0) > 0.7 else "keep_both",
                "user_decision": "pending",  # Will be set by user
            })
        else:
            synthesis_decisions.append({
                "new_concept": ext,
                "matches": [],
                "recommended_action": "create_new",
                "user_decision": "pending",
            })
    
    logger.info(
        "synthesize_node: Complete",
        num_decisions=len(synthesis_decisions),
        num_with_matches=len([d for d in synthesis_decisions if d["matches"]]),
    )
    
    return {
        "synthesis_decisions": synthesis_decisions,
        "awaiting_user_approval": True,
    }


async def user_review_node(state: IngestionState) -> dict:
    """
    Node 4b: Wait for user review (interrupt point).
    
    Uses LangGraph 1.0 `interrupt()` function to pause execution.
    """
    logger.info("user_review_node: Checking review requirement")
    
    # For auto-approval mode (if skip_review is set), approve all
    if state.get("skip_review", False):
        decisions = state.get("synthesis_decisions", [])
        approved = [d["new_concept"] for d in decisions if d["recommended_action"] != "skip"]
        
        logger.info("user_review_node: Auto-approved", num_approved=len(approved))
        return {
            "user_approved_concepts": approved,
            "awaiting_user_approval": False,
        }
    
    # Pause for user input
    logger.info("user_review_node: Interrupting for user review")
    
    user_response = interrupt({
        "type": "review_concepts",
        "synthesis_decisions": state.get("synthesis_decisions", []),
        "message": "Please review the extracted concepts",
    })
    
    # Resume logic (runs when Command(resume=...) is sent)
    logger.info("user_review_node: Resumed with user response")
    
    if user_response.get("cancelled"):
        return {"user_cancelled": True, "awaiting_user_approval": False}
    
    return {
        "user_approved_concepts": user_response.get("approved_concepts", []),
        "awaiting_user_approval": False,
    }


async def create_concepts_node(state: IngestionState) -> dict:
    """
    Node 5: Create concept nodes in Neo4j.
    
    Input: extracted_concepts OR user_approved_concepts, note_id, user_id
    Output: created_concept_ids
    """
    logger.info("create_concepts_node: Starting")
    
    # Use approved concepts if available, otherwise use extracted
    concepts = state.get("user_approved_concepts") or state.get("extracted_concepts", [])
    note_id = state.get("note_id")
    user_id = state.get("user_id", "default_user")
    
    if not concepts:
        return {"created_concept_ids": []}
    
    try:
        neo4j = await get_neo4j_client()
        concept_ids = []
        
        for concept in concepts:
            concept_id = str(uuid.uuid4())
            
            # Create concept node
            query = """
            MERGE (c:Concept {name: $name})
            ON CREATE SET
                c.id = $id,
                c.definition = $definition,
                c.domain = $domain,
                c.complexity_score = $complexity_score,
                c.created_at = datetime(),
                c.user_id = $user_id
            ON MATCH SET
                c.definition = CASE WHEN c.definition IS NULL OR c.definition = '' 
                               THEN $definition ELSE c.definition END,
                c.updated_at = datetime()
            RETURN c.id AS concept_id
            """
            
            result = await neo4j.execute_query(
                query,
                {
                    "id": concept_id,
                    "name": concept.get("name", "Unknown"),
                    "definition": concept.get("definition", ""),
                    "domain": concept.get("domain", "General"),
                    "complexity_score": float(concept.get("complexity_score", 5)),
                    "user_id": user_id,
                },
            )
            
            if result:
                concept_ids.append(result[0].get("concept_id", concept_id))
            else:
                concept_ids.append(concept_id)
        
        # Create relationships between concepts in the same note
        for i, cid in enumerate(concept_ids):
            for jid in concept_ids[i + 1:]:
                await neo4j.execute_query(
                    """
                    MATCH (c1:Concept {id: $id1}), (c2:Concept {id: $id2})
                    MERGE (c1)-[r:RELATED_TO]->(c2)
                    SET r.strength = 0.7, r.source = 'co-occurrence'
                    """,
                    {"id1": cid, "id2": jid},
                )
        
        # Link note to concepts
        if note_id:
            for cid in concept_ids:
                await neo4j.execute_query(
                    """
                    MERGE (n:NoteSource {id: $note_id})
                    WITH n
                    MATCH (c:Concept {id: $concept_id})
                    MERGE (n)-[r:EXPLAINS]->(c)
                    SET r.relevance = 0.9
                    """,
                    {"note_id": note_id, "concept_id": cid},
                )
        
        logger.info(
            "create_concepts_node: Complete",
            num_created=len(concept_ids),
        )
        
        return {"created_concept_ids": concept_ids}
        
    except Exception as e:
        logger.error("create_concepts_node: Failed", error=str(e))
        return {"created_concept_ids": [], "error": str(e)}


async def link_synthesis_node(state: IngestionState) -> dict:
    """
    Node 6: Link new concepts to existing related ones.
    
    Called after synthesis to create cross-references.
    
    Input: created_concept_ids, related_concepts
    Output: synthesis_completed
    """
    logger.info("link_synthesis_node: Starting")
    
    new_ids = state.get("created_concept_ids", [])
    related = state.get("related_concepts", [])
    
    if not new_ids or not related:
        return {"synthesis_completed": True}
    
    try:
        neo4j = await get_neo4j_client()
        
        # Link new concepts to related existing ones
        for new_id in new_ids[:5]:  # Limit connections
            for rel in related[:3]:
                rel_id = rel.get("id")
                if rel_id and rel_id != new_id:
                    await neo4j.execute_query(
                        """
                        MATCH (c1:Concept {id: $id1}), (c2:Concept {id: $id2})
                        MERGE (c1)-[r:RELATED_TO]->(c2)
                        SET r.strength = 0.6, r.source = 'synthesis'
                        """,
                        {"id1": new_id, "id2": rel_id},
                    )
        
        logger.info("link_synthesis_node: Complete")
        return {"synthesis_completed": True}
        
    except Exception as e:
        logger.error("link_synthesis_node: Failed", error=str(e))
        return {"synthesis_completed": False, "error": str(e)}


async def generate_flashcards_node(state: IngestionState) -> dict:
    """
    Node 7: Generate flashcards from extracted concepts.
    
    Input: extracted_concepts, note_id, user_id
    Output: flashcard_ids
    """
    logger.info("generate_flashcards_node: Starting")
    
    # Use approved or extracted concepts
    concepts = state.get("user_approved_concepts") or state.get("extracted_concepts", [])
    note_id = state.get("note_id")
    user_id = state.get("user_id", "default_user")
    raw_content = state.get("raw_content", "")
    
    if not concepts:
        return {"flashcard_ids": []}
    
    concept_names = [c.get("name", "") for c in concepts]
    
    prompt = f"""Generate flashcards from this note.

Content:
{raw_content[:2000]}

Key concepts:
{', '.join(concept_names)}

Instructions:
1. Create 3-5 CLOZE DELETION flashcards
2. Hide important terms with [___]
3. Make context clear enough to answer
4. Focus on key facts and concepts

Return ONLY valid JSON:
{{
    "flashcards": [
        {{
            "question": "Text with [___] for the missing term",
            "answer": "The missing term",
            "concept": "Related concept name"
        }}
    ]
}}
"""
    
    try:
        response = await llm_flashcard.ainvoke(prompt)
        content = response.content.strip()
        
        if content.startswith("```json"):
            content = content.split("```json")[1].split("```")[0].strip()
        elif content.startswith("```"):
            content = content.split("```")[1].split("```")[0].strip()
        
        data = json.loads(content)
        flashcards = data.get("flashcards", [])
        
        pg_client = await get_postgres_client()
        card_ids = []
        
        for card in flashcards:
            card_id = str(uuid.uuid4())
            
            await pg_client.execute(
                """
                INSERT INTO flashcards (id, user_id, note_id, question, answer, 
                                        card_type, next_review, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                uuid.UUID(card_id),
                user_id,
                uuid.UUID(note_id) if note_id else None,
                card.get("question", ""),
                card.get("answer", ""),
                "cloze",
                datetime.utcnow() + timedelta(days=1),
                datetime.utcnow(),
            )
            
            card_ids.append(card_id)
        
        logger.info(
            "generate_flashcards_node: Complete",
            num_flashcards=len(card_ids),
        )
        
        return {"flashcard_ids": card_ids}
        
    except Exception as e:
        logger.error("generate_flashcards_node: Failed", error=str(e))
        return {"flashcard_ids": []}


# ============================================================================
# Routing Functions (Conditional Edges)
# ============================================================================


def route_after_find_related(state: IngestionState) -> Literal["synthesize", "create_concepts"]:
    """
    Route based on overlap detection.
    
    If significant overlap found -> go to synthesis
    Otherwise -> go directly to concept creation
    """
    needs_synthesis = state.get("needs_synthesis", False)
    skip_review = state.get("skip_review", False)
    
    if needs_synthesis and not skip_review:
        logger.info("route_after_find_related: Routing to synthesis")
        return "synthesize"
    else:
        logger.info("route_after_find_related: Routing to create_concepts (no overlap)")
        return "create_concepts"


def route_after_user_review(state: IngestionState) -> Literal["create_concepts", "end"]:
    """
    Route based on user review decision.
    
    If user approved -> continue to creation
    If user cancelled -> end workflow
    """
    awaiting = state.get("awaiting_user_approval", False)
    user_cancelled = state.get("user_cancelled", False)
    
    if user_cancelled:
        logger.info("route_after_user_review: User cancelled, ending workflow")
        return "end"
    
    if not awaiting:
        logger.info("route_after_user_review: User approved, continuing")
        return "create_concepts"
    
    # Still waiting - this shouldn't happen if interrupt works correctly
    return "end"


# ============================================================================
# Graph Construction
# ============================================================================


def create_ingestion_graph(enable_interrupts: bool = True):
    """
    Build the ingestion workflow graph with conditional edges.
    
    Flow:
    START → extract_concepts → store_note → find_related 
          → (conditional) → [needs_synthesis? → synthesize → user_review → ...]
                          → [no_overlap → create_concepts → ...]
          → link_synthesis → generate_flashcards → END
    
    Args:
        enable_interrupts: Whether to enable human-in-the-loop interrupts
    """
    builder = StateGraph(IngestionState)
    
    # Add nodes
    builder.add_node("extract_concepts", extract_concepts_node)
    builder.add_node("store_note", store_note_node)
    builder.add_node("find_related", find_related_node)
    builder.add_node("synthesize", synthesize_node)
    builder.add_node("user_review", user_review_node)
    builder.add_node("create_concepts", create_concepts_node)
    builder.add_node("link_synthesis", link_synthesis_node)
    builder.add_node("generate_flashcards", generate_flashcards_node)
    
    # Linear edges (always executed)
    builder.add_edge(START, "extract_concepts")
    builder.add_edge("extract_concepts", "store_note")
    builder.add_edge("store_note", "find_related")
    
    # Conditional edge: Route based on overlap detection
    builder.add_conditional_edges(
        "find_related",
        route_after_find_related,
        {
            "synthesize": "synthesize",
            "create_concepts": "create_concepts",
        }
    )
    
    # Synthesis path
    builder.add_edge("synthesize", "user_review")
    builder.add_conditional_edges(
        "user_review",
        route_after_user_review,
        {
            "create_concepts": "create_concepts",
            "end": END,
        }
    )
    
    # Convergence: both paths lead to create_concepts → link → flashcards
    builder.add_edge("create_concepts", "link_synthesis")
    builder.add_edge("link_synthesis", "generate_flashcards")
    builder.add_edge("generate_flashcards", END)
    
    # Get checkpointer (MemorySaver for dev, PostgresSaver for prod)
    checkpointer = get_checkpointer()
    
    # Compile (interrupt() function handles pausing now, so no interrupt_before needed)
    return builder.compile(checkpointer=checkpointer)


# Global graph instance
ingestion_graph = create_ingestion_graph()

# ingestion_graph_auto is deprecated as single graph handles both modes now but keeping alias for safety
ingestion_graph_auto = ingestion_graph


# ============================================================================
# Public Interface
# ============================================================================


async def run_ingestion(
    content: str,
    title: Optional[str] = None,
    user_id: str = "default_user",
    note_id: Optional[str] = None,
    skip_review: bool = False,
) -> dict:
    """
    Run the ingestion workflow for a note.
    
    Args:
        content: Raw markdown/text content
        title: Optional note title
        user_id: User ID
        note_id: Optional existing note ID (for updates)
        skip_review: If True, auto-approve all concepts (no human-in-the-loop)
    
    Returns:
        Dict with note_id, concept_ids, flashcard_ids, thread_id
    """
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state: IngestionState = {
        "user_id": user_id,
        "raw_content": content,
        "title": title,
        "note_id": note_id,
        "skip_review": skip_review,
        "extracted_concepts": [],
        "related_concepts": [],
        "needs_synthesis": False,
        "synthesis_completed": False,
        "created_concept_ids": [],
        "flashcard_ids": [],
        "error": None,
    }
    
    logger.info(
        "run_ingestion: Starting workflow",
        thread_id=thread_id,
        content_length=len(content),
        skip_review=skip_review,
    )
    
    try:
        # Use auto graph if skipping review
        graph = ingestion_graph_auto if skip_review else ingestion_graph
        
        result = await graph.ainvoke(initial_state, config)
        
        # Check if workflow is paused for user review
        if result.get("awaiting_user_approval"):
            logger.info(
                "run_ingestion: Paused for user review",
                thread_id=thread_id,
            )
            return {
                "note_id": result.get("note_id"),
                "concepts": result.get("extracted_concepts", []),
                "synthesis_decisions": result.get("synthesis_decisions", []),
                "status": "awaiting_review",
                "thread_id": thread_id,
            }
        
        logger.info(
            "run_ingestion: Complete",
            note_id=result.get("note_id"),
            num_concepts=len(result.get("created_concept_ids", [])),
            num_flashcards=len(result.get("flashcard_ids", [])),
        )
        
        return {
            "note_id": result.get("note_id"),
            "concepts": result.get("extracted_concepts", []),
            "concept_ids": result.get("created_concept_ids", []),
            "flashcard_ids": result.get("flashcard_ids", []),
            "status": "completed",
            "thread_id": thread_id,
            "error": result.get("error"),
        }
        
    except Exception as e:
        logger.error("run_ingestion: Failed", error=str(e))
        return {
            "note_id": note_id,
            "concepts": [],
            "concept_ids": [],
            "flashcard_ids": [],
            "status": "error",
            "thread_id": thread_id,
            "error": str(e),
        }


async def resume_ingestion(
    thread_id: str,
    user_approved_concepts: Optional[list[dict]] = None,
    user_cancelled: bool = False,
) -> dict:
    """
    Resume a paused ingestion workflow after user review.
    
    Args:
        thread_id: The thread ID from the initial run
        user_approved_concepts: Concepts approved by the user
        user_cancelled: If True, cancel the workflow
    
    Returns:
        Dict with final results
    """
    config = {"configurable": {"thread_id": thread_id}}
    
    logger.info(
        "resume_ingestion: Resuming workflow",
        thread_id=thread_id,
        num_approved=len(user_approved_concepts or []),
        cancelled=user_cancelled,
    )
    
    try:
        # Resume using Command pattern
        resume_value = {
            "approved_concepts": user_approved_concepts or [],
            "cancelled": user_cancelled
        }
        
        result = await ingestion_graph.ainvoke(Command(resume=resume_value), config)
        
        logger.info(
            "resume_ingestion: Complete",
            note_id=result.get("note_id"),
            num_concepts=len(result.get("created_concept_ids", [])),
        )
        
        return {
            "note_id": result.get("note_id"),
            "concept_ids": result.get("created_concept_ids", []),
            "flashcard_ids": result.get("flashcard_ids", []),
            "status": "completed" if not user_cancelled else "cancelled",
            "thread_id": thread_id,
        }
        
    except Exception as e:
        logger.error("resume_ingestion: Failed", error=str(e))
        return {
            "status": "error",
            "thread_id": thread_id,
            "error": str(e),
        }


async def get_ingestion_status(thread_id: str) -> dict:
    """
    Get the current status of an ingestion workflow.
    
    Args:
        thread_id: The thread ID from the initial run
    
    Returns:
        Dict with current state and status
    """
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        state = ingestion_graph.get_state(config)
        
        if not state:
            return {"status": "not_found", "thread_id": thread_id}
        
        values = state.values
        next_nodes = state.next if hasattr(state, "next") else []
        
        if values.get("awaiting_user_approval"):
            status = "awaiting_review"
        elif values.get("error"):
            status = "error"
        elif not next_nodes:
            status = "completed"
        else:
            status = "processing"
        
        return {
            "status": status,
            "thread_id": thread_id,
            "note_id": values.get("note_id"),
            "next_step": next_nodes[0] if next_nodes else None,
            "concepts": values.get("extracted_concepts", []),
            "synthesis_decisions": values.get("synthesis_decisions"),
        }
        
    except Exception as e:
        logger.error("get_ingestion_status: Failed", error=str(e))
        return {"status": "error", "thread_id": thread_id, "error": str(e)}
