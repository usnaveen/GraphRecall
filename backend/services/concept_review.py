"""Concept Review Service - Human-in-the-Loop for concept extraction.

This service manages the workflow where:
1. AI extracts concepts from notes
2. User reviews and can modify/add/remove concepts
3. User approves and concepts are added to knowledge graph
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import structlog

from backend.models.feed_schemas import (
    ConceptReviewItem,
    ConceptReviewSession,
    ConceptReviewApproval,
)

logger = structlog.get_logger()


# In-memory session store (in production, use Redis or database)
_review_sessions: dict[str, ConceptReviewSession] = {}


class ConceptReviewService:
    """Service for managing concept review sessions."""
    
    def __init__(self, pg_client, neo4j_client):
        self.pg_client = pg_client
        self.neo4j_client = neo4j_client
    
    async def create_review_session(
        self,
        user_id: str,
        note_id: str,
        original_content: str,
        extracted_concepts: list[dict],
        conflicts: list[dict],
    ) -> ConceptReviewSession:
        """
        Create a new review session for extracted concepts.
        
        Args:
            user_id: User ID
            note_id: ID of the ingested note
            original_content: Original note content
            extracted_concepts: Concepts extracted by the AI
            conflicts: Detected conflicts from synthesis agent
            
        Returns:
            ConceptReviewSession for the user to review
        """
        # Build conflict lookup
        conflict_map = {}
        for c in conflicts:
            conflict_map[c.get("new_concept_name")] = c
        
        # Convert extracted concepts to review items
        review_items = []
        for concept in extracted_concepts:
            # Check if this concept has a conflict
            conflict = conflict_map.get(concept["name"])
            
            is_duplicate = False
            matched_id = None
            
            if conflict:
                if conflict.get("decision") == "DUPLICATE":
                    is_duplicate = True
                    matched_id = conflict.get("matched_concept_id")
            
            review_items.append(ConceptReviewItem(
                id=concept.get("id", str(uuid4())),
                name=concept["name"],
                definition=concept.get("definition", ""),
                domain=concept.get("domain", "General"),
                complexity_score=concept.get("complexity_score", 5),
                confidence=concept.get("confidence", 0.8),
                related_concepts=concept.get("related_concepts", []),
                prerequisites=concept.get("prerequisites", []),
                is_selected=not is_duplicate,  # Deselect duplicates by default
                is_duplicate=is_duplicate,
                matched_existing_id=matched_id,
            ))
        
        # Create session
        session = ConceptReviewSession(
            user_id=user_id,
            note_id=note_id,
            original_content=original_content,
            concepts=review_items,
            conflicts=conflicts,
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        
        # Store session
        _review_sessions[session.session_id] = session
        
        # Also persist to database for durability
        try:
            await self.pg_client.execute_insert(
                """
                INSERT INTO concept_review_sessions 
                    (id, user_id, note_id, status, concepts_json, created_at, expires_at)
                VALUES 
                    (:id, :user_id, :note_id, :status, :concepts_json, :created_at, :expires_at)
                ON CONFLICT (id) DO UPDATE SET
                    status = :status,
                    concepts_json = :concepts_json
                RETURNING id
                """,
                {
                    "id": session.session_id,
                    "user_id": user_id,
                    "note_id": note_id,
                    "status": "pending",
                    "concepts_json": session.model_dump_json(),
                    "created_at": session.created_at,
                    "expires_at": session.expires_at,
                },
            )
        except Exception as e:
            logger.warning(
                "ConceptReviewService: Failed to persist session to DB",
                error=str(e),
            )
        
        logger.info(
            "ConceptReviewService: Review session created",
            session_id=session.session_id,
            num_concepts=len(review_items),
        )
        
        return session
    
    async def get_session(self, session_id: str) -> Optional[ConceptReviewSession]:
        """
        Get a review session by ID.
        
        Args:
            session_id: Session ID
            
        Returns:
            ConceptReviewSession or None if not found/expired
        """
        # Try in-memory first
        session = _review_sessions.get(session_id)
        
        if session:
            # Check expiration
            if session.expires_at < datetime.now(timezone.utc):
                logger.info(
                    "ConceptReviewService: Session expired",
                    session_id=session_id,
                )
                del _review_sessions[session_id]
                return None
            return session
        
        # Try database
        try:
            result = await self.pg_client.execute_query(
                """
                SELECT concepts_json
                FROM concept_review_sessions
                WHERE id = :session_id
                  AND expires_at > NOW()
                  AND status = 'pending'
                """,
                {"session_id": session_id},
            )
            
            if result:
                import json
                session_data = json.loads(result[0]["concepts_json"])
                session = ConceptReviewSession(**session_data)
                _review_sessions[session_id] = session  # Cache it
                return session
                
        except Exception as e:
            logger.error(
                "ConceptReviewService: Error fetching session from DB",
                error=str(e),
            )
        
        return None
    
    async def update_session(
        self,
        session_id: str,
        concepts: list[ConceptReviewItem],
    ) -> Optional[ConceptReviewSession]:
        """
        Update a review session with modified concepts.
        
        Args:
            session_id: Session ID
            concepts: Updated list of concepts
            
        Returns:
            Updated ConceptReviewSession or None
        """
        session = await self.get_session(session_id)
        if not session:
            return None
        
        # Mark modified concepts
        for concept in concepts:
            concept.user_modified = True
        
        session.concepts = concepts
        _review_sessions[session_id] = session
        
        # Update in database
        try:
            await self.pg_client.execute_insert(
                """
                UPDATE concept_review_sessions
                SET concepts_json = :concepts_json
                WHERE id = :session_id
                """,
                {
                    "session_id": session_id,
                    "concepts_json": session.model_dump_json(),
                },
            )
        except Exception as e:
            logger.warning(
                "ConceptReviewService: Failed to update session in DB",
                error=str(e),
            )
        
        return session
    
    async def approve_session(
        self,
        approval: ConceptReviewApproval,
    ) -> dict:
        """
        Approve a review session and commit concepts to the knowledge graph.
        
        Args:
            approval: User's approval with modified concepts
            
        Returns:
            Result dictionary with counts
        """
        session = await self.get_session(approval.session_id)
        if not session:
            raise ValueError(f"Session not found: {approval.session_id}")
        
        if session.status != "pending":
            raise ValueError(f"Session already processed: {session.status}")
        
        logger.info(
            "ConceptReviewService: Approving session",
            session_id=approval.session_id,
            approved_count=len(approval.approved_concepts),
            removed_count=len(approval.removed_concept_ids),
            added_count=len(approval.added_concepts),
        )
        
        # Import the graph builder
        from backend.agents.graph_builder import GraphBuilderAgent
        
        graph_builder = GraphBuilderAgent()
        
        # Prepare final concept list
        final_concepts = []
        
        # Add approved concepts (excluding removed ones)
        for concept in approval.approved_concepts:
            if concept.id not in approval.removed_concept_ids and concept.is_selected:
                final_concepts.append({
                    "id": concept.id,
                    "name": concept.name,
                    "definition": concept.definition,
                    "domain": concept.domain,
                    "complexity_score": concept.complexity_score,
                    "confidence": concept.confidence,
                    "related_concepts": concept.related_concepts,
                    "prerequisites": concept.prerequisites,
                })
        
        # Add user-added concepts
        for concept in approval.added_concepts:
            final_concepts.append({
                "id": str(uuid4()),
                "name": concept.name,
                "definition": concept.definition,
                "domain": concept.domain,
                "complexity_score": concept.complexity_score,
                "confidence": 1.0,  # User added = full confidence
                "related_concepts": concept.related_concepts,
                "prerequisites": concept.prerequisites,
            })
        
        # Build the graph
        result = await graph_builder.build(
            concepts=final_concepts,
            conflicts=[],  # Already resolved by user
            note_id=session.note_id,
        )
        
        # Update session status
        session.status = "approved"
        _review_sessions[approval.session_id] = session
        
        try:
            await self.pg_client.execute_insert(
                """
                UPDATE concept_review_sessions
                SET status = 'approved',
                    concepts_json = :concepts_json
                WHERE id = :session_id
                """,
                {
                    "session_id": approval.session_id,
                    "concepts_json": session.model_dump_json(),
                },
            )
        except Exception as e:
            logger.warning(
                "ConceptReviewService: Failed to update session status in DB",
                error=str(e),
            )
        
        logger.info(
            "ConceptReviewService: Session approved",
            session_id=approval.session_id,
            concepts_created=result["concepts_created"],
            relationships_created=result["relationships_created"],
        )
        
        return {
            "session_id": approval.session_id,
            "concepts_created": result["concepts_created"],
            "relationships_created": result["relationships_created"],
            "status": "approved",
        }
    
    async def cancel_session(self, session_id: str) -> bool:
        """
        Cancel a review session without committing changes.
        
        Args:
            session_id: Session ID
            
        Returns:
            True if cancelled, False if not found
        """
        session = await self.get_session(session_id)
        if not session:
            return False
        
        session.status = "cancelled"
        
        # Remove from cache
        if session_id in _review_sessions:
            del _review_sessions[session_id]
        
        # Update in database
        try:
            await self.pg_client.execute_insert(
                """
                UPDATE concept_review_sessions
                SET status = 'cancelled'
                WHERE id = :session_id
                """,
                {"session_id": session_id},
            )
        except Exception as e:
            logger.warning(
                "ConceptReviewService: Failed to cancel session in DB",
                error=str(e),
            )
        
        logger.info(
            "ConceptReviewService: Session cancelled",
            session_id=session_id,
        )
        
        return True
    
    async def get_pending_sessions(self, user_id: str) -> list[ConceptReviewSession]:
        """
        Get all pending review sessions for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            List of pending sessions
        """
        pending = []
        
        # Check in-memory cache
        for session in _review_sessions.values():
            if session.user_id == user_id and session.status == "pending":
                if session.expires_at > datetime.now(timezone.utc):
                    pending.append(session)
        
        # Also check database
        try:
            result = await self.pg_client.execute_query(
                """
                SELECT concepts_json
                FROM concept_review_sessions
                WHERE user_id = :user_id
                  AND status = 'pending'
                  AND expires_at > NOW()
                ORDER BY created_at DESC
                """,
                {"user_id": user_id},
            )
            
            import json
            for row in result:
                session_data = json.loads(row["concepts_json"])
                session = ConceptReviewSession(**session_data)
                # Add if not already in list
                if not any(s.session_id == session.session_id for s in pending):
                    pending.append(session)
                    
        except Exception as e:
            logger.warning(
                "ConceptReviewService: Error fetching pending sessions",
                error=str(e),
            )
        
        return pending
