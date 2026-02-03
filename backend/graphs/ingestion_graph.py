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
from datetime import datetime, timedelta, timezone
from typing import Optional, Literal

import structlog
from backend.config.llm import get_chat_model
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

from backend.agents.states import IngestionState
from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.graphs.checkpointer import get_checkpointer

logger = structlog.get_logger()

# ============================================================================
# LLM Configuration (Gemini)
# ============================================================================

llm_extraction = get_chat_model(temperature=0.2)
llm_flashcard = get_chat_model(temperature=0.3)

# ============================================================================
# Node Functions
# ============================================================================


from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.extraction import ExtractionAgent
from backend.agents.synthesis import SynthesisAgent
from backend.agents.content_generator import ContentGeneratorAgent

# Initialize agents
extraction_agent = ExtractionAgent(temperature=0.2)
synthesis_agent = SynthesisAgent()
content_generator = ContentGeneratorAgent()

async def extract_concepts_node(state: IngestionState) -> dict:
    """
    Node 1: Extract concepts from raw content using ExtractionAgent.
    """
    content = state.get("raw_content", "")
    logger.info("extract_concepts_node: Starting", content_length=len(content))
    
    is_image = content.startswith("data:image")

    # Build processing metadata
    meta = state.get("processing_metadata") or {}
    meta["content_length"] = len(content)
    meta["is_multimodal"] = is_image
    meta["input_type"] = "image" if is_image else "text"
    meta["extraction_agent"] = "ExtractionAgent (Gemini, temp=0.2)"

    try:
        # Fetch existing concept names so the LLM can reference them in
        # related_concepts / prerequisites (enables cross-note linking)
        existing_concept_names: list[str] = []
        try:
            user_id = state.get("user_id", "default_user")
            neo4j = await get_neo4j_client()
            existing = await neo4j.execute_query(
                "MATCH (c:Concept) WHERE c.user_id = $user_id RETURN c.name AS name LIMIT 200",
                {"user_id": user_id},
            )
            existing_concept_names = [c["name"] for c in existing if c.get("name")]
        except Exception as e:
            logger.warning("extract_concepts_node: Context retrieval failed", error=str(e))
            pass  # Continue without context if Neo4j is unavailable

        if existing_concept_names:
            result = await extraction_agent.extract_with_context(content, existing_concept_names)
        else:
            result = await extraction_agent.extract(content)
        concepts = [c.model_dump() for c in result.concepts]

        # Enrich metadata with extraction results
        meta["concepts_extracted"] = len(concepts)
        meta["domains_detected"] = list({c.get("domain", "General") for c in concepts})
        meta["concept_names"] = [c.get("name", "") for c in concepts]
        avg_complexity = sum(c.get("complexity_score", 5) for c in concepts) / max(len(concepts), 1)
        meta["avg_complexity"] = round(avg_complexity, 1)

        logger.info("extract_concepts_node: Complete", num_concepts=len(concepts))

        return {"extracted_concepts": concepts, "processing_metadata": meta}
        
    except Exception as e:
        logger.error("extract_concepts_node: Failed", error=str(e))
        return {"extracted_concepts": [], "error": str(e), "processing_metadata": meta}


async def store_note_node(state: IngestionState) -> dict:
    """
    Node 2: Store the note in PostgreSQL.
    """
    note_id = state.get("note_id") or str(uuid.uuid4())
    user_id = state.get("user_id", "default_user")
    
    logger.info("store_note_node: Storing note", note_id=note_id)
    
    try:
        pg_client = await get_postgres_client()
        
        # Insert or update note using named params
        await pg_client.execute_insert(
            """
            INSERT INTO notes (id, user_id, title, content_text, content_hash, created_at, updated_at)
            VALUES (:id, :user_id, :title, :content_text, :content_hash, :created_at, :created_at)
            ON CONFLICT (id) DO UPDATE SET
                content_text = :content_text,
                content_hash = :content_hash,
                updated_at = :created_at
            RETURNING id
            """,
            {
                "id": note_id,
                "user_id": user_id,
                "title": state.get("title") or "Untitled Note",
                "content_text": state.get("raw_content", ""),
                "content_hash": state.get("content_hash"), # Save hash
                "created_at": datetime.now(timezone.utc),
            }
        )
        
        logger.info("store_note_node: Complete", note_id=note_id)
        return {"note_id": note_id}
        
    except Exception as e:
        logger.error("store_note_node: Failed", error=str(e))
        return {"note_id": note_id, "error": str(e)}


async def find_related_node(state: IngestionState) -> dict:
    """
    Node 3: Find existing concepts related to the extracted ones.
    """
    logger.info("find_related_node: Starting")
    
    extracted = state.get("extracted_concepts", [])
    if not extracted:
        return {"related_concepts": [], "needs_synthesis": False, "overlap_ratio": 0.0}
    
    try:
        neo4j = await get_neo4j_client()
        user_id = state.get("user_id", "default_user")
        
        # Get all existing concepts for user
        query = """
        MATCH (c:Concept)
        WHERE c.user_id = $user_id
        RETURN c.id AS id, c.name AS name, c.definition AS definition, 
               c.domain AS domain, c.complexity_score AS complexity_score
        LIMIT 100
        """
        
        existing = await neo4j.execute_query(query, {"user_id": user_id})
        
        if not existing:
            logger.info("find_related_node: No existing concepts")
            return {"related_concepts": [], "needs_synthesis": False, "overlap_ratio": 0.0}
        
        # Simple name matching for MVP
        related = []
        extracted_names = [c.get("name", "").lower() for c in extracted]
        
        for concept in existing:
            name = concept.get("name", "").lower()
            for ext_name in extracted_names:
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
        
        # Enrich processing metadata
        meta = state.get("processing_metadata") or {}
        meta["existing_concepts_scanned"] = len(existing)
        meta["overlap_ratio"] = round(overlap_ratio, 2)
        meta["related_concept_names"] = [r.get("name", "") for r in related[:5]]

        return {
            "related_concepts": related,
            "needs_synthesis": needs_synthesis,
            "overlap_ratio": overlap_ratio,
            "processing_metadata": meta,
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
    Node 4a: Synthesize new concepts with existing ones using SynthesisAgent.
    """
    logger.info("synthesize_node: Starting synthesis analysis")
    
    extracted = state.get("extracted_concepts", [])
    related = state.get("related_concepts", [])
    
    try:
        result = await synthesis_agent.analyze(extracted, related)
        
        # Convert output to decision format expected by frontend
        synthesis_decisions = []
        for decision in result.decisions:
            # Find original concept data
            original = next((c for c in extracted if c["name"] == decision.new_concept_name), {"name": decision.new_concept_name})
            new_concept = original.copy()
            
            # If matched, store ID for potential merge
            if decision.matched_concept_id:
                new_concept["existing_id"] = decision.matched_concept_id

            synthesis_decisions.append({
                "new_concept": new_concept,
                "matches": [{"existing_name": decision.matched_concept_id}] if decision.matched_concept_id else [],
                "recommended_action": decision.merge_strategy.value.lower() if hasattr(decision.merge_strategy, 'value') else str(decision.merge_strategy),
                "reasoning": decision.reasoning,
                "user_decision": "pending",
            })
            
        logger.info("synthesize_node: Complete", num_decisions=len(synthesis_decisions))
        
        return {
            "synthesis_decisions": synthesis_decisions,
            "awaiting_user_approval": True,
        }
    except Exception as e:
        logger.error("synthesize_node: Failed", error=str(e))
        # Fallback to empty if fails
        return {
            "synthesis_decisions": [],
            "awaiting_user_approval": True, # Still pause so user sees failure? Or just proceed?
        }


async def user_review_node(state: IngestionState) -> dict:
    """
    Node 4b: Wait for user review (interrupt point).
    """
    logger.info("user_review_node: Checking review requirement")
    
    if state.get("skip_review", False):
        decisions = state.get("synthesis_decisions", [])
        approved = []
        
        for d in decisions:
            action = d.get("recommended_action", "create_new").lower()
            concept = d["new_concept"]
            
            # Skip duplicates/rejected
            if action in ["skip", "reject"]:
                continue
                
            # For merge/enhance, ensure we point to the existing ID
            if action in ["merge", "enhance", "duplicate"] and concept.get("existing_id"):
                concept["id"] = concept["existing_id"]
                
            approved.append(concept)
            
        logger.info("user_review_node: Auto-approved", num_approved=len(approved))
        return {
            "user_approved_concepts": approved,
            "awaiting_user_approval": False,
        }
    
    logger.info("user_review_node: Interrupting for user review")
    
    user_response = interrupt({
        "type": "review_concepts",
        "synthesis_decisions": state.get("synthesis_decisions", []),
        "message": "Please review the extracted concepts",
    })
    
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
    """
    logger.info("create_concepts_node: Starting")
    
    concepts = state.get("user_approved_concepts") or state.get("extracted_concepts", [])
    note_id = state.get("note_id")
    user_id = state.get("user_id", "default_user")
    
    if not concepts:
        return {"created_concept_ids": []}
    
    try:
        neo4j = await get_neo4j_client()
        concept_ids = []
        
        for concept in concepts:
            # Call create_concept with correct signature
            # Use concept.get("id") if present (from merge logic), otherwise None (generates new UUID)
            result_node = await neo4j.create_concept(
                name=concept.get("name", "Unknown"),
                definition=concept.get("definition", ""),
                domain=concept.get("domain", "General"),
                complexity_score=float(concept.get("complexity_score", 5)),
                user_id=user_id,
                concept_id=concept.get("id"),
                # embedding=None (for now)
            )
            # Neo4j RETURN c gives {"c": {node_props}} — extract the node dict
            node_data = result_node.get("c", result_node) if isinstance(result_node, dict) else {}
            # If node_data is a Neo4j Node object, convert to dict
            if hasattr(node_data, 'items'):
                concept_ids.append(node_data.get("id"))
            else:
                concept_ids.append(str(node_data) if node_data else None)
        
        # Create relationships based on extraction (Semantic)
        # Build lookup from current batch
        name_to_id = {c.get("name", "").lower(): cid for c, cid in zip(concepts, concept_ids)}

        # Also fetch ALL existing user concepts for cross-note linking
        existing_concepts = await neo4j.execute_query(
            "MATCH (c:Concept) WHERE c.user_id = $user_id RETURN c.id AS id, c.name AS name",
            {"user_id": user_id},
        )
        existing_name_to_id = {c["name"].lower(): c["id"] for c in existing_concepts if c.get("name")}
        # Merge: current batch takes priority, then existing concepts
        all_name_to_id = {**existing_name_to_id, **name_to_id}

        relationships_created = 0
        for concept, cid in zip(concepts, concept_ids):
             # Handle related_concepts — search ALL existing concepts, not just current batch
             for related_name in concept.get("related_concepts", []):
                 r_name = related_name
                 if isinstance(related_name, dict):
                     r_name = related_name.get("name")

                 if isinstance(r_name, str):
                     r_id = all_name_to_id.get(r_name.lower())
                     if r_id and r_id != cid:
                         try:
                             await neo4j.create_relationship(
                                 from_concept_id=cid,
                                 to_concept_id=r_id,
                                 relationship_type="RELATED_TO",
                                 user_id=user_id,
                                 properties={"strength": 0.8, "source": "extraction"}
                             )
                             relationships_created += 1
                         except Exception as e:
                            logger.error("create_concepts_node: Failed to create RELATED_TO relationship", from_id=cid, to_id=r_id, error=str(e), exc_info=True)
                            # Skip if relationship creation fails

             # Handle prerequisites — search ALL existing concepts
             for prereq_name in concept.get("prerequisites", []):
                 p_name = prereq_name
                 if isinstance(prereq_name, dict):
                     p_name = prereq_name.get("name")

                 if isinstance(p_name, str):
                     p_id = all_name_to_id.get(p_name.lower())
                     if p_id and p_id != cid:
                         try:
                             await neo4j.create_relationship(
                                 from_concept_id=p_id,
                                 to_concept_id=cid,
                                 relationship_type="PREREQUISITE_OF",
                                 user_id=user_id,
                                 properties={"strength": 0.9, "source": "extraction"}
                             )
                             relationships_created += 1
                         except Exception:
                             pass

        logger.info("create_concepts_node: Relationships created", count=relationships_created)
        
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
        
        # Enrich processing metadata with graph stats
        meta = state.get("processing_metadata") or {}
        meta["concepts_created"] = len(concept_ids)
        # Count relationships created (co-occurrence pairs + explicit)
        num_cooccurrence = max(0, len(concept_ids) * (len(concept_ids) - 1) // 2)
        meta["relationships_created"] = num_cooccurrence

        logger.info(
            "create_concepts_node: Complete",
            num_created=len(concept_ids),
        )

        return {"created_concept_ids": concept_ids, "processing_metadata": meta}
        
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
            concept_name = card.get("concept", "")
            
            # Find concept_id from name (from our extracted concepts)
            concept_id = None
            for c in concepts:
                if c.get("name", "").lower() == concept_name.lower():
                    concept_id = c.get("id", concept_name)
                    break
            if not concept_id:
                concept_id = concept_name  # Use name as fallback
            
            await pg_client.execute_update(
                """
                INSERT INTO flashcards (id, user_id, concept_id, front_content, back_content,
                                        difficulty, source_note_ids, created_at)
                VALUES (:id, :user_id, :concept_id, :front_content, :back_content,
                        :difficulty, :source_note_ids, :created_at)
                """,
                {
                    "id": card_id,
                    "user_id": user_id,
                    "concept_id": concept_id,
                    "front_content": card.get("question", ""),
                    "back_content": card.get("answer", ""),
                    "difficulty": 0.5,
                    "source_note_ids": [note_id] if note_id else [],
                    "created_at": datetime.now(timezone.utc),
                }
            )
            
            card_ids.append(card_id)
        
        # Enrich processing metadata
        meta = state.get("processing_metadata") or {}
        meta["flashcards_generated"] = len(card_ids)
        meta["flashcard_agent"] = "Gemini (temp=0.3)"

        logger.info(
            "generate_flashcards_node: Complete",
            num_flashcards=len(card_ids),
        )

        return {"flashcard_ids": card_ids, "processing_metadata": meta}
        
    except Exception as e:
        logger.error("generate_flashcards_node: Failed", error=str(e))
        return {"flashcard_ids": []}


async def generate_quiz_node(state: IngestionState) -> dict:
    """
    Node 8: Generate quizzes (MCQs) from extracted concepts (Persistence Layer).
    
    Input: user_approved_concepts/extracted_concepts, user_id
    Output: quiz_ids
    """
    logger.info("generate_quiz_node: Starting")
    
    concepts = state.get("user_approved_concepts") or state.get("extracted_concepts", [])
    user_id = state.get("user_id", "default_user")
    
    if not concepts:
         return {"quiz_ids": []}
         
    try:
        # Generate MCQs for valid concepts
        # Filter concepts that have at least a name and definition
        valid_concepts = [
            c for c in concepts 
            if c.get("name") and c.get("definition")
        ]
        
        # Batch generate MCQs using ContentGeneratorAgent
        # We generate 2 MCQs per concept to populate the DB
        mcqs = await content_generator.generate_mcq_batch(
            valid_concepts, 
            num_per_concept=2
        )
        
        if not mcqs:
            return {"quiz_ids": []}
            
        pg_client = await get_postgres_client()
        quiz_ids = []
        
        for mcq in mcqs:
            q_id = str(uuid.uuid4())
            
            # Find concept_id
            concept_id = mcq.concept_id
            # If concept_id is missing or name-only, try to resolve to UUID from creation step
            if not concept_id or concept_id == mcq.concept_id: # (if equal to name)
                 # Try to find matching concept in our list which might have 'id' now
                 for c in concepts:
                     if c.get("name") == mcq.concept_id: # or however it was mapped
                        if c.get("id"):
                            concept_id = c.get("id")
                            break
            
            # Fallback if still no UUID (shouldn't happen if create_concepts ran)
            if not concept_id:
                concept_id = "unknown"

            # Insert into quizzes table
            await pg_client.execute_update(
                """
                INSERT INTO quizzes (id, user_id, concept_id, question_text, question_type, 
                                     options_json, correct_answer, explanation, created_at)
                VALUES (:id, :user_id, :concept_id, :question_text, 'mcq',
                        :options_json, :correct_answer, :explanation, :created_at)
                """,
                {
                    "id": q_id,
                    "user_id": user_id,
                    "concept_id": concept_id,
                    "question_text": mcq.question,
                    "options_json": json.dumps([o.model_dump() for o in mcq.options]),
                    "correct_answer": next((o.id for o in mcq.options if o.is_correct), "A"),
                    "explanation": mcq.explanation,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            quiz_ids.append(q_id)
            
        # Enrich processing metadata
        meta = state.get("processing_metadata") or {}
        meta["quizzes_generated"] = len(quiz_ids)
        
        logger.info("generate_quiz_node: Complete", num_quizzes=len(quiz_ids))
        
        return {"quiz_ids": quiz_ids, "processing_metadata": meta}

    except Exception as e:
        logger.error("generate_quiz_node: Failed", error=str(e))
        return {"quiz_ids": []}


# ============================================================================
# Routing Functions (Conditional Edges)
# ============================================================================


def route_after_find_related(state: IngestionState) -> Literal["synthesize", "create_concepts"]:
    """
    Route based on overlap detection.

    If significant overlap found AND review not skipped -> go to synthesis
    Otherwise -> go directly to concept creation (fast path)
    """
    needs_synthesis = state.get("needs_synthesis", False)
    skip_review = state.get("skip_review", False)

    if needs_synthesis and not skip_review:
        logger.info(
            "route_after_find_related: Routing to synthesis",
            reason="overlap_detected",
        )
        return "synthesize"
    else:
        logger.info(
            "route_after_find_related: Routing to create_concepts (fast path)",
            needs_synthesis=needs_synthesis,
            skip_review=skip_review,
        )
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
    builder.add_node("generate_quiz", generate_quiz_node)
    
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
    builder.add_edge("generate_flashcards", "generate_quiz")
    builder.add_edge("generate_quiz", END)
    
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
    content_hash: Optional[str] = None, # New arg
) -> dict:
    """
    Run the ingestion workflow for a note.
    
    Args:
        content: Raw markdown/text content
        title: Optional note title
        user_id: User ID
        note_id: Optional existing note ID (for updates)
        skip_review: If True, auto-approve all concepts (no human-in-the-loop)
        content_hash: SHA-256 hash of content for deduplication
    
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
        "content_hash": content_hash, # Pass to state
        "extracted_concepts": [],
        "related_concepts": [],
        "needs_synthesis": False,
        "synthesis_completed": False,
        "created_concept_ids": [],
        "flashcard_ids": [],
        "quiz_ids": [],
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
                "processing_metadata": result.get("processing_metadata", {}),
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
            "quiz_ids": result.get("quiz_ids", []),
            "processing_metadata": result.get("processing_metadata", {}),
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
    user_id: Optional[str] = None,
) -> dict:
    """
    Resume a paused ingestion workflow after user review.
    
    Args:
        thread_id: The thread ID from the initial run
        user_approved_concepts: Concepts approved by the user
        user_cancelled: If True, cancel the workflow
        user_id: Optional user ID to verify ownership
    
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
        # Check ownership if user_id provided
        if user_id:
            state = ingestion_graph.get_state(config)
            if state and state.values.get("user_id") != user_id:
                logger.warning(
                    "resume_ingestion: Unauthorized access attempt",
                    thread_id=thread_id,
                    user_id=user_id,
                )
                return {"status": "error", "error": "Unauthorized access to thread"}

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


async def get_ingestion_status(thread_id: str, user_id: Optional[str] = None) -> dict:
    """
    Get the current status of an ingestion workflow.
    
    Args:
        thread_id: The thread ID from the initial run
        user_id: Optional user ID to verify ownership
    
    Returns:
        Dict with current state and status
    """
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        state = ingestion_graph.get_state(config)
        
        if not state:
            return {"status": "not_found", "thread_id": thread_id}
        
        values = state.values
        
        # Check ownership
        if user_id and values.get("user_id") != user_id:
            logger.warning(
                "get_ingestion_status: Unauthorized access attempt",
                thread_id=thread_id,
                user_id=user_id,
            )
            return {"status": "not_found", "thread_id": thread_id}
            
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
