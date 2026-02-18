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
from backend.agents.proposition_agent import PropositionExtractionAgent
from backend.services.ingestion import DocumentParserService, BookChunker
from backend.services.ingestion.embedding_service import EmbeddingService

# Initialize agents
extraction_agent = ExtractionAgent(temperature=0.2)
synthesis_agent = SynthesisAgent()
content_generator = ContentGeneratorAgent()

# Initialize services
parser_service = DocumentParserService()
book_chunker = BookChunker(max_chars=1400, overlap_ratio=0.15)
embedding_service = EmbeddingService()
proposition_agent = PropositionExtractionAgent()

# ... (parse_node, chunk_node, embed_node remain unchanged) ...

async def extract_propositions_node(state: IngestionState) -> dict:
    """
    Node 0d: Extract atomic propositions from chunks (Phase 3).
    
    DISABLED: Proposition extraction is expensive (1 LLM call per chunk).
    The benefit is marginal - flashcard/quiz generation works well with concepts alone.
    This node now returns empty propositions, allowing the fallback paths to be used.
    
    To re-enable: uncomment the original implementation below.
    """
    logger.info("extract_propositions_node: SKIPPED (disabled for cost optimization)")
    return {"propositions": []}
    
    # --- ORIGINAL IMPLEMENTATION (disabled) ---
    # logger.info("extract_propositions_node: Starting")
    # chunks = state.get("chunks", [])
    # if not chunks:
    #     return {}
    #     
    # all_propositions = []
    # 
    # # Process each chunk group (Parent + Children)
    # for group in chunks:
    #     child_contents = group.get("child_contents", [])
    #     child_ids = group.get("child_ids", [])
    #     
    #     for i, (content, child_id) in enumerate(zip(child_contents, child_ids)):
    #         try:
    #             temp_chunk = Chunk(
    #                 id=uuid.UUID(child_id),
    #                 note_id=uuid.UUID(str(state["note_id"])),
    #                 content=content,
    #                 chunk_index=i,
    #                 created_at=datetime.now(timezone.utc)
    #             )
    #             props = await proposition_agent.extract_propositions(temp_chunk)
    #             if props:
    #                 props_dicts = [p.model_dump() | {"id": str(uuid.uuid4())} for p in props]
    #                 all_propositions.extend(props_dicts)
    #         except Exception as e:
    #             logger.warning("extract_propositions_node: Failed", chunk_id=child_id, error=str(e))
    #             continue
    #
    # logger.info("extract_propositions_node: Done", count=len(all_propositions))
    # return {"propositions": all_propositions}

async def parse_node(state: IngestionState) -> dict:
    """
    Node 0a: Parse document into Markdown.
    """
    logger.info("parse_node: Starting")
    raw_content = state.get("raw_content", "")
    filename = state.get("title", "unknown")
    file_type = state.get("file_type", "txt")
    
    try:
        # Convert string content to bytes if needed (simple hack for now)
        # In real scenario, we might pass file path or bytes buffer
        content_bytes = raw_content.encode("utf-8")
        
        parsed = await parser_service.parse_document(content_bytes, filename, file_type)
        
        meta = state.get("processing_metadata") or {}
        meta["parser"] = parsed.metadata.get("source", "simple")
        meta["pages"] = parsed.metadata.get("pages", 1)
        
        return {
            "parsed_document": parsed.model_dump(),
            "processing_metadata": meta
        }
    except Exception as e:
        logger.error("parse_node: Failed", error=str(e))
        return {"error": str(e)}

async def chunk_node(state: IngestionState) -> dict:
    """
    Node 0b: Split parsed document into chunks using BookChunker.

    Uses the unified BookChunker (image-aware, heading-preserving) for all
    content types — notes, articles, and books alike.

    Output format matches what downstream nodes expect:
    Each group = {parent_id, parent_content, parent_index,
                  child_contents, child_ids, child_embeddings (later),
                  images (list of image metadata)}
    """
    logger.info("chunk_node: Starting")

    parsed = state.get("parsed_document")
    raw_content = state.get("raw_content", "")
    if not parsed and not raw_content:
        return {"chunks": []}

    # Get markdown text
    if parsed:
        from backend.services.ingestion.parser_service import ParsedDocument
        doc_obj = ParsedDocument(**parsed)
        md_text = doc_obj.markdown_content
    else:
        md_text = raw_content

    if not md_text:
        return {"chunks": []}

    note_id = state.get("note_id") or str(uuid.uuid4())

    # Use BookChunker for all content (notes + books)
    raw_chunks = book_chunker.chunk_text(md_text)

    # Convert BookChunker output to the group format expected by downstream nodes.
    # BookChunker produces flat chunks; we treat each as a "parent" with itself as
    # the single "child" (preserving the parent/child DB schema).
    # For larger chunks we could split children further, but for notes this is fine.
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    child_splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)

    chunks = []
    for chunk in raw_chunks:
        parent_id = str(uuid.uuid4())
        parent_text = chunk.text

        # Split parent into smaller children for embedding
        child_texts = child_splitter.split_text(parent_text)
        if not child_texts:
            child_texts = [parent_text]

        child_ids = [str(uuid.uuid4()) for _ in child_texts]

        # Image metadata from BookChunker
        images = [
            {
                "filename": img.filename,
                "caption": img.caption,
                "page": img.page,
                "url": img.url,
            }
            for img in chunk.images
        ] if chunk.images else []

        chunks.append({
            "parent_id": parent_id,
            "parent_content": parent_text,
            "parent_index": chunk.index,
            "parent_page_start": chunk.images[0].page if chunk.images else None,
            "parent_page_end": chunk.images[-1].page if chunk.images else None,
            "child_contents": child_texts,
            "child_ids": child_ids,
            "child_page_starts": [None] * len(child_texts),
            "child_page_ends": [None] * len(child_texts),
            "images": images,
            "headings": chunk.headings,
        })

    logger.info("chunk_node: Complete", num_groups=len(chunks),
                total_children=sum(len(c["child_contents"]) for c in chunks))
    return {"chunks": chunks, "note_id": note_id}

async def embed_node(state: IngestionState) -> dict:
    """
    Node 0c: Generate embeddings for child chunks.
    """
    logger.info("embed_node: Starting")
    chunks = state.get("chunks", [])
    if not chunks:
        return {}

    # Collect all child texts for batch embedding
    all_child_texts = []
    # Map (parent_idx, child_idx) -> flat_index
    index_map = []

    for p_idx, group in enumerate(chunks):
        for c_idx, content in enumerate(group["child_contents"]):
            all_child_texts.append(content)
            index_map.append((p_idx, c_idx))

    if not all_child_texts:
        return {}

    embeddings = await embedding_service.embed_batch(all_child_texts)

    # Initialize child_embeddings lists
    for group in chunks:
        group["child_embeddings"] = []

    if not embeddings:
        logger.error(
            "embed_node: All embeddings failed! Chunks will be saved without embeddings.",
            total_texts=len(all_child_texts),
        )
        # Fill with None so save_chunks_node can still save the text
        for p_idx, c_idx in index_map:
            chunks[p_idx]["child_embeddings"].append(None)
    elif len(embeddings) != len(all_child_texts):
        logger.warning(
            "embed_node: Partial embedding failure",
            expected=len(all_child_texts),
            received=len(embeddings),
        )
        for i, (p_idx, c_idx) in enumerate(index_map):
            emb = embeddings[i] if i < len(embeddings) else None
            # Treat empty list placeholders from failed individual embeds as None
            if emb is not None and len(emb) == 0:
                emb = None
            chunks[p_idx]["child_embeddings"].append(emb)
    else:
        for i, emb in enumerate(embeddings):
            p_idx, c_idx = index_map[i]
            # Treat empty list placeholders as None
            if emb is not None and len(emb) == 0:
                emb = None
            chunks[p_idx]["child_embeddings"].append(emb)

    embedded_count = sum(
        1 for group in chunks
        for emb in group["child_embeddings"]
        if emb is not None
    )
    logger.info(
        "embed_node: Complete",
        total_chunks=len(all_child_texts),
        embedded=embedded_count,
        missing=len(all_child_texts) - embedded_count,
    )

    return {"chunks": chunks}

async def save_chunks_node(state: IngestionState) -> dict:
    """
    Node 0d: Save generated chunks to PostgreSQL.
    """
    chunks = state.get("chunks", [])
    if not chunks:
        return {}
        
    logger.info("save_chunks_node: Saving chunks", count=len(chunks))
    
    try:
        pg_client = await get_postgres_client()
        saved_count = 0
        
        for parent_group in chunks:
            # Use pre-generated ID or fallback (though chunk_node should guarantee it now)
            parent_id = parent_group.get("parent_id") or str(uuid.uuid4())
            parent_text = parent_group["parent_content"]
            parent_page_start = parent_group.get("parent_page_start")
            parent_page_end = parent_group.get("parent_page_end")
            
            # Save Parent Chunk (with images metadata from BookChunker)
            images_json = json.dumps(parent_group.get("images", []))
            await pg_client.execute_update(
                """
                INSERT INTO chunks (id, note_id, content, chunk_level, chunk_index, page_start, page_end, images, created_at)
                VALUES (:id, :note_id, :content, 'parent', :index, :page_start, :page_end, :images, :created_at)
                ON CONFLICT (id) DO NOTHING
                """,
                {
                    "id": parent_id,
                    "note_id": state["note_id"],
                    "content": parent_text,
                    "index": parent_group["parent_index"],
                    "images": images_json,
                    "page_start": parent_page_start,
                    "page_end": parent_page_end,
                    "created_at": datetime.now(timezone.utc)
                }
            )
            saved_count += 1
            
            # Save Child Chunks
            child_contents = parent_group["child_contents"]
            child_embeddings = parent_group.get("child_embeddings", [None] * len(child_contents))
            child_ids = parent_group.get("child_ids", [str(uuid.uuid4()) for _ in child_contents])
            child_page_starts = parent_group.get("child_page_starts", [None] * len(child_contents))
            child_page_ends = parent_group.get("child_page_ends", [None] * len(child_contents))
            
            for i, (child_text, embedding, child_id) in enumerate(zip(child_contents, child_embeddings, child_ids)):
                page_start = child_page_starts[i] if i < len(child_page_starts) else None
                page_end = child_page_ends[i] if i < len(child_page_ends) else None

                if not embedding:
                    logger.warning(
                        "save_chunks_node: Saving child chunk WITHOUT embedding (RAG will skip this chunk)",
                        chunk_id=child_id,
                        note_id=state["note_id"],
                        chunk_index=i,
                    )

                # Dynamic query based on whether embedding exists
                if embedding:
                    # Format embedding as pgvector-compatible literal string
                    embedding_literal = "[" + ",".join(str(x) for x in embedding) + "]"
                    await pg_client.execute_update(
                        """
                        INSERT INTO chunks (id, note_id, parent_chunk_id, content, chunk_level, chunk_index, page_start, page_end, embedding, created_at)
                        VALUES (:id, :note_id, :parent_id, :content, 'child', :index, :page_start, :page_end, cast(:embedding as vector), :created_at)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        {
                            "id": child_id,
                            "note_id": state["note_id"],
                            "parent_id": parent_id,
                            "content": child_text,
                            "index": i,
                            "page_start": page_start,
                            "page_end": page_end,
                            "embedding": embedding_literal,
                            "created_at": datetime.now(timezone.utc)
                        }
                    )
                else:
                    await pg_client.execute_update(
                        """
                        INSERT INTO chunks (id, note_id, parent_chunk_id, content, chunk_level, chunk_index, page_start, page_end, created_at)
                        VALUES (:id, :note_id, :parent_id, :content, 'child', :index, :page_start, :page_end, :created_at)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        {
                            "id": child_id,
                            "note_id": state["note_id"],
                            "parent_id": parent_id,
                            "content": child_text,
                            "index": i,
                            "page_start": page_start,
                            "page_end": page_end,
                            "created_at": datetime.now(timezone.utc)
                        }
                    )
                saved_count += 1
        
        # Save Propositions (if any)
        propositions = state.get("propositions", [])
        if propositions:
            logger.info("save_chunks_node: Saving propositions", count=len(propositions))
            for prop in propositions:
                # Use pre-generated ID if available
                prop_id = prop.get("id") or str(uuid.uuid4())
                
                await pg_client.execute_update(
                    """
                    INSERT INTO propositions (id, note_id, chunk_id, content, confidence, is_atomic, created_at)
                    VALUES (:id, :note_id, :chunk_id, :content, :confidence, :is_atomic, :created_at)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    {
                        "id": prop_id,
                        "note_id": str(prop["note_id"]),
                        "chunk_id": str(prop["chunk_id"]),
                        "content": prop["content"],
                        "confidence": prop["confidence"],
                        "is_atomic": prop["is_atomic"],
                        "created_at": datetime.now(timezone.utc)
                    }
                )
        
        logger.info("save_chunks_node: Saved chunks", saved=saved_count, propositions_saved=len(propositions))
        return {}
        
    except Exception as e:
        logger.error("save_chunks_node: Failed", error=str(e))
        return {"error": str(e)}

async def extract_concepts_node(state: IngestionState) -> dict:
    """
    Node 1: Extract concepts from raw content using ExtractionAgent.
    """
    logger.info("extract_concepts_node: Starting")

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

    # Prefer chunks context if available (better context management)
    chunks = state.get("chunks", [])
    
    import asyncio
    
    # --- Batching Logic (Fixes timeouts / truncation) ---
    if chunks:
        # Group chunks into manageable batches to avoid 100k+ char prompts
        # Target: ~25k chars per batch (safe for flash model, fast)
        BATCH_CHAR_LIMIT = 25000
        
        batches = []
        current_batch_texts = []
        current_batch_len = 0
        
        # Prepare batches
        for c in chunks:
            text = c.get("parent_content", "")
            # If adding this chunk exceeds limit (and batch not empty), start new batch
            if current_batch_len + len(text) > BATCH_CHAR_LIMIT and current_batch_texts:
                batches.append("\n\n".join(current_batch_texts))
                current_batch_texts = []
                current_batch_len = 0
                
            current_batch_texts.append(text)
            current_batch_len += len(text)
            
        # Add final batch
        if current_batch_texts:
            batches.append("\n\n".join(current_batch_texts))
            
        logger.info("extract_concepts_node: Processing in batches", 
                    num_batches=len(batches), total_chunks=len(chunks))

        # --- Parallel Execution ---
        # Limit concurrency to avoid rate limits
        semaphore = asyncio.Semaphore(5) 
        all_concepts = []
        
        async def process_batch(batch_text: str, batch_idx: int):
            async with semaphore:
                try:
                    # Retrieve context if available (only for first few batches to save time?)
                    # For now, use context if available for all
                    if existing_concept_names:
                        res = await extraction_agent.extract_with_context(batch_text, existing_concept_names)
                    else:
                        res = await extraction_agent.extract(batch_text)
                    return res.concepts
                except Exception as e:
                    logger.error("extract_concepts_node: Batch failed", batch=batch_idx, error=str(e))
                    return []

        # Launch tasks
        tasks = [process_batch(text, i) for i, text in enumerate(batches)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Aggregate results
        for res in results:
            if isinstance(res, list): # List of concepts
                all_concepts.extend([c.model_dump() for c in res])
            else:
                logger.error("extract_concepts_node: Unexpected result type", type=type(res))

    else:
        # Fallback for non-chunked content (e.g. short text / URL)
        content = state.get("raw_content", "")
        # ... logic for single extraction ...
        logger.info("extract_concepts_node: Single extraction", length=len(content))
        
        try:
            if existing_concept_names:
                result = await extraction_agent.extract_with_context(content, existing_concept_names)
            else:
                result = await extraction_agent.extract(content)
            all_concepts = [c.model_dump() for c in result.concepts]
        except Exception as e:
            logger.error("extract_concepts_node: Single extraction failed", error=str(e))
            all_concepts = []

    # Common Post-Processing
    concepts = all_concepts
    
    # Deduplicate by name (case-insensitive) just in case
    unique_concepts = {}
    for c in concepts:
        key = c["name"].lower().strip()
        if key not in unique_concepts:
            unique_concepts[key] = c
    concepts = list(unique_concepts.values())

    meta = state.get("processing_metadata") or {}
    meta["concepts_extracted"] = len(concepts)
    meta["domains_detected"] = list({c.get("domain", "General") for c in concepts})
    meta["concept_names"] = [c.get("name", "") for c in concepts]
    avg_complexity = sum(c.get("complexity_score", 5) for c in concepts) / max(len(concepts), 1)
    meta["avg_complexity"] = round(avg_complexity, 1)

    logger.info("extract_concepts_node: Complete", num_concepts=len(concepts))
    return {"extracted_concepts": concepts, "processing_metadata": meta}


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
        resource_type = state.get("resource_type") or "notes"
        await pg_client.execute_insert(
            """
            INSERT INTO notes (id, user_id, title, content_text, content_hash, resource_type, created_at, updated_at)
            VALUES (:id, :user_id, :title, :content_text, :content_hash, :resource_type, :created_at, :created_at)
            ON CONFLICT (id) DO UPDATE SET
                content_text = :content_text,
                content_hash = :content_hash,
                resource_type = :resource_type,
                updated_at = :created_at
            RETURNING id
            """,
            {
                "id": note_id,
                "user_id": user_id,
                "title": state.get("title") or "Untitled Note",
                "content_text": state.get("raw_content", ""),
                "content_hash": state.get("content_hash"), # Save hash
                "resource_type": resource_type,
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
               c.domain AS domain, c.complexity_score AS complexity_score,
               c.confidence AS confidence
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
                confidence=float(concept.get("confidence", 0.8)),
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

        concept_evidence = {
            cid: concept.get("evidence_span")
            for concept, cid in zip(concepts, concept_ids)
        }
        
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

        async def upsert_relationship(
            from_id: str,
            to_id: str,
            rel_type: str,
            base_strength: float,
            source: str = "extraction",
            increment: float = 0.1,
        ) -> None:
            await neo4j.execute_query(
                f"""
                MATCH (from:Concept {{id: $from_id, user_id: $uid}})
                MATCH (to:Concept {{id: $to_id, user_id: $uid}})
                MERGE (from)-[r:{rel_type}]->(to)
                ON CREATE SET r.strength = $base_strength,
                              r.source = $source,
                              r.mention_count = 1,
                              r.created_at = datetime()
                ON MATCH SET r.mention_count = coalesce(r.mention_count, 1) + 1,
                             r.strength = CASE
                                 WHEN coalesce(r.strength, $base_strength) + $increment > 1.0 THEN 1.0
                                 ELSE coalesce(r.strength, $base_strength) + $increment
                             END,
                             r.source = coalesce(r.source, $source),
                             r.updated_at = datetime()
                """,
                {
                    "from_id": from_id,
                    "to_id": to_id,
                    "uid": user_id,
                    "base_strength": base_strength,
                    "increment": increment,
                    "source": source,
                },
            )
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
                             await upsert_relationship(
                                 from_id=cid,
                                 to_id=r_id,
                                 rel_type="RELATED_TO",
                                 base_strength=0.8,
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
                             await upsert_relationship(
                                 from_id=p_id,
                                 to_id=cid,
                                 rel_type="PREREQUISITE_OF",
                                 base_strength=0.9,
                             )
                             relationships_created += 1
                         except Exception:
                             pass

             # Handle SUBTOPIC_OF (child -> parent)
             parent_topic = concept.get("parent_topic")
             if parent_topic and isinstance(parent_topic, str):
                 parent_id = all_name_to_id.get(parent_topic.lower())
                 if parent_id and parent_id != cid:
                     try:
                         await upsert_relationship(
                             from_id=cid,
                             to_id=parent_id,
                             rel_type="SUBTOPIC_OF",
                             base_strength=1.0,
                         )
                         relationships_created += 1
                     except Exception:
                         pass

             # Handle subtopics (subtopic -> this concept)
             for sub_name in concept.get("subtopics", []):
                 s_name = sub_name if isinstance(sub_name, str) else sub_name.get("name", "")
                 if isinstance(s_name, str):
                     s_id = all_name_to_id.get(s_name.lower())
                     if s_id and s_id != cid:
                         try:
                             await upsert_relationship(
                                 from_id=s_id,
                                 to_id=cid,
                                 rel_type="SUBTOPIC_OF",
                                 base_strength=1.0,
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
                    MERGE (n:NoteSource {id: $note_id, user_id: $user_id})
                    WITH n
                    MATCH (c:Concept {id: $concept_id, user_id: $user_id})
                    MERGE (n)-[r:EXPLAINS]->(c)
                    SET r.relevance = 0.9,
                        r.evidence_span = CASE
                            WHEN $evidence_span IS NULL OR $evidence_span = ""
                            THEN r.evidence_span
                            ELSE $evidence_span
                        END
                    """,
                    {
                        "note_id": note_id,
                        "concept_id": cid,
                        "user_id": user_id,
                        "evidence_span": concept_evidence.get(cid),
                    },
                )
        
        # Link note to propositions (Phase 3)
        propositions = state.get("propositions", [])
        if note_id and propositions:
            logger.info("create_concepts_node: Syncing propositions to Neo4j", count=len(propositions))
            
            # Prepare params for batch creation
            prop_params = []
            for p in propositions:
                # Use existing ID if available (should be set in extract_propositions_node)
                p_id = str(p.get("id")) if p.get("id") else str(uuid.uuid4())
                prop_params.append({
                    "id": p_id,
                    "content": p.get("content", "")[:500],
                    "confidence": p.get("confidence", 0.0)
                })

            await neo4j.execute_query(
                """
                MERGE (n:NoteSource {id: $note_id})
                WITH n
                UNWIND $props AS p
                MERGE (prop:Proposition {id: p.id})
                SET prop.content = p.content, prop.confidence = p.confidence
                MERGE (n)-[r:HAS_PROPOSITION]->(prop)
                """,
                {"note_id": note_id, "props": prop_params}
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
        user_id = state.get("user_id", "default_user")

        # Link new concepts to related existing ones using upsert pattern
        # to be consistent with create_concepts_node strength reinforcement
        for new_id in new_ids[:5]:  # Limit connections
            for rel in related[:3]:
                rel_id = rel.get("id")
                if rel_id and rel_id != new_id:
                    await neo4j.execute_query(
                        """
                        MATCH (c1:Concept {id: $id1, user_id: $uid})
                        MATCH (c2:Concept {id: $id2, user_id: $uid})
                        MERGE (c1)-[r:RELATED_TO]->(c2)
                        ON CREATE SET r.strength = 0.6,
                                      r.source = 'synthesis',
                                      r.mention_count = 1,
                                      r.created_at = datetime()
                        ON MATCH SET r.mention_count = coalesce(r.mention_count, 1) + 1,
                                     r.strength = CASE
                                         WHEN coalesce(r.strength, 0.6) + 0.1 > 1.0 THEN 1.0
                                         ELSE coalesce(r.strength, 0.6) + 0.1
                                     END,
                                     r.updated_at = datetime()
                        """,
                        {"id1": new_id, "id2": rel_id, "uid": user_id},
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
    Output: term_card_ids
    """
    logger.info("generate_flashcards_node: Starting")
    
    # Use approved or extracted concepts
    concepts = state.get("user_approved_concepts") or state.get("extracted_concepts", [])
    note_id = state.get("note_id")
    user_id = state.get("user_id", "default_user")
    raw_content = state.get("raw_content", "")
    
    if not concepts:
        return {"term_card_ids": []}
    
    propositions = state.get("propositions", [])
    
    # PHASE 4: PROPOSITION-ENHANCED GENERATION
    # If we have atomic propositions, use them for high-precision cards
    if propositions:
        logger.info("generate_flashcards_node: Using propositions for generation", count=len(propositions))
        try:
            # Generate Cloze Deletion cards from atomic facts
            flashcards_dicts = await content_generator.generate_cloze_from_propositions(
                propositions, 
                count=5
            )
        except Exception as e:
            logger.error("generate_flashcards_node: Proposition generation failed, falling back", error=str(e))
            flashcards_dicts = []
    else:
        # Fallback to legacy generation (using raw content)
        flashcards_dicts = [] # Placeholder to trigger legacy flow if I keep it? 
        # Actually let's just use the legacy flow if prop generation fails or is empty.
    
    # Legacy flow (if no propositions or they failed)
    if not propositions or not flashcards_dicts:
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
            "front": "Text with [___] for the missing term",
            "back": "The missing term",
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
            flashcards_dicts = data.get("flashcards", [])
        except json.JSONDecodeError:
            # LLM sometimes produces invalid escape sequences (e.g. \n inside strings).
            # Try to sanitise before giving up.
            try:
                import re
                # Replace lone backslashes not followed by a valid JSON escape char
                sanitised = re.sub(r'\\(?!["\\bfnrtu/])', r'\\\\', content)
                data = json.loads(sanitised)
                flashcards_dicts = data.get("flashcards", [])
            except Exception:
                logger.error("generate_flashcards_node: Legacy generation failed", error="JSON parse failed after sanitisation")
                return {"term_card_ids": []}

    # Save cards (Unified path)
    if not flashcards_dicts:
        return {"term_card_ids": []}
        
    try:
        pg_client = await get_postgres_client()
        card_ids = []
        
        for card in flashcards_dicts:
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
                    "front_content": card.get("front") or card.get("question", ""),
                    "back_content": card.get("back") or card.get("answer", ""),
                    "difficulty": 0.5,
                    "source_note_ids": [note_id] if note_id else [],
                    "created_at": datetime.now(timezone.utc),
                }
            )
            
            card_ids.append(card_id)
        
        # Enrich processing metadata
        meta = state.get("processing_metadata") or {}
        meta["flashcards_generated"] = len(card_ids)
        if propositions:
             meta["flashcard_mode"] = "proposition_cloze"

        logger.info(
            "generate_flashcards_node: Complete",
            num_flashcards=len(card_ids),
        )

        return {"term_card_ids": card_ids, "processing_metadata": meta}
        
    except Exception as e:
        logger.error("generate_flashcards_node: Save failed", error=str(e))
        return {"term_card_ids": []}


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
        
        # Prepare concepts with propositions context
        propositions = state.get("propositions", [])
        prop_contents = [p["content"] for p in propositions if "content" in p]
        
        enriched_concepts = []
        for c in valid_concepts:
            # Shallow copy to avoid mutating state
            c_copy = c.copy()
            # Attach ALL propositions for this note as context (simple approach)
            # In future, we could filter by keyword relevance to the concept
            c_copy["propositions"] = prop_contents
            enriched_concepts.append(c_copy)
            
        # Batch generate MCQs using ContentGeneratorAgent
        # We generate 2 MCQs per concept to populate the DB
        mcqs = await content_generator.generate_mcq_batch(
            enriched_concepts, 
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

    # Force review/synthesis path if not explicitly skipped
    # This ensures user always gets to confirm extracted concepts
    if not skip_review:
        logger.info(
            "route_after_find_related: Routing to synthesis (Force Review)",
            reason="manual_review_required",
        )
        return "synthesize"
    
    # Auto-pilot path (only if skip_review=True)
    if needs_synthesis:
        logger.info(
            "route_after_find_related: Routing to synthesis (Auto-resolve)",
            reason="overlap_detected_skipping_review",
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
    builder.add_node("parse", parse_node)
    builder.add_node("chunk", chunk_node)
    builder.add_node("extract_propositions", extract_propositions_node)
    builder.add_node("embed_chunks", embed_node)
    builder.add_node("save_chunks", save_chunks_node)
    builder.add_node("extract_concepts", extract_concepts_node)
    
    # ... existing nodes ...
    builder.add_node("store_note", store_note_node)
    builder.add_node("find_related", find_related_node)
    builder.add_node("synthesize", synthesize_node)
    builder.add_node("user_review", user_review_node)
    builder.add_node("create_concepts", create_concepts_node)
    builder.add_node("link_synthesis", link_synthesis_node)
    builder.add_node("generate_flashcards", generate_flashcards_node)
    builder.add_node("generate_quiz", generate_quiz_node)
    
    # New Flow:
    # START -> parse -> chunk -> extract_concepts -> store_note -> embed_chunks -> save_chunks -> ...
    # NOTE: store_note MUST run before save_chunks due to FK constraint (chunks.note_id -> notes.id)
    
    builder.add_edge(START, "parse")
    builder.add_edge("parse", "chunk")
    builder.add_edge("chunk", "extract_concepts")
    builder.add_edge("extract_concepts", "store_note")  # Store note FIRST
    builder.add_edge("store_note", "embed_chunks")       # Then embed
    builder.add_edge("embed_chunks", "save_chunks")      # Then save chunks (FK safe)
    builder.add_edge("save_chunks", "find_related")
    
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
    # Conditional checkpointer: Skip in LangGraph Studio (it provides its own), use in production
    import sys
    is_langgraph_api = "langgraph_api" in sys.modules
    if is_langgraph_api:
        # Running in LangGraph Studio/Cloud - persistence is automatic
        return builder.compile()
    else:
        # Local dev or production - use our checkpointer for persistence
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
    resource_type: Optional[str] = None, # e.g. "book", "notes"
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
        resource_type: Optional resource type (e.g. "book", "notes", "article")

    Returns:
        Dict with note_id, concept_ids, term_card_ids, thread_id
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
        "resource_type": resource_type, # Pass to state
        "extracted_concepts": [],
        "related_concepts": [],
        "needs_synthesis": False,
        "synthesis_completed": False,
        "created_concept_ids": [],
        "term_card_ids": [],
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
                "note_id": str(result.get("note_id")) if result.get("note_id") else None,
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
            num_flashcards=len(result.get("term_card_ids", [])),
        )
        
        return {
            "note_id": str(result.get("note_id")) if result.get("note_id") else None,
            "concepts": result.get("extracted_concepts", []),
            "concept_ids": result.get("created_concept_ids", []),
            "term_card_ids": result.get("term_card_ids", []),
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
            "term_card_ids": [],
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
            "term_card_ids": result.get("term_card_ids", []),
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
