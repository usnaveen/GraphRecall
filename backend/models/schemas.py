"""Pydantic models for GraphRecall API and internal data structures."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ============================================================================
# Enums
# ============================================================================


class ContentType(str, Enum):
    """Type of note content."""

    TEXT = "text"
    MARKDOWN = "markdown"
    PDF = "pdf"
    HANDWRITING = "handwriting"


class ConflictDecision(str, Enum):
    """Decision type for concept conflicts."""

    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    ENHANCE = "ENHANCE"
    NEW = "NEW"


class MergeStrategy(str, Enum):
    """Strategy for handling concept conflicts."""

    SKIP = "SKIP"
    MERGE = "MERGE"
    FLAG_FOR_REVIEW = "FLAG_FOR_REVIEW"
    CREATE_NEW = "CREATE_NEW"


class GraphOperationType(str, Enum):
    """Type of graph operation."""

    CREATE_CONCEPT = "CREATE_CONCEPT"
    UPDATE_CONCEPT = "UPDATE_CONCEPT"
    CREATE_RELATIONSHIP = "CREATE_RELATIONSHIP"
    DELETE_RELATIONSHIP = "DELETE_RELATIONSHIP"


class RelationshipType(str, Enum):
    """Types of relationships between concepts."""

    PREREQUISITE_OF = "PREREQUISITE_OF"
    RELATED_TO = "RELATED_TO"
    BUILDS_ON = "BUILDS_ON"


# ============================================================================
# Core Domain Models
# ============================================================================


class ConceptBase(BaseModel):
    """Base model for concept data."""

    name: str = Field(..., description="Name of the concept")
    definition: str = Field(..., description="Brief definition of the concept")
    domain: str = Field(..., description="Subject area or field")
    complexity_score: float = Field(
        default=5.0, ge=1.0, le=10.0, description="Complexity rating 1-10"
    )


class ConceptCreate(ConceptBase):
    """Model for creating a new concept."""

    confidence: float = Field(
        default=0.8, ge=0.0, le=1.0, description="Extraction confidence score"
    )
    related_concepts: list[str] = Field(
        default_factory=list, description="Names of related concepts"
    )
    prerequisites: list[str] = Field(
        default_factory=list, description="Names of prerequisite concepts"
    )


class Concept(ConceptBase):
    """Full concept model with ID and metadata."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    related_concepts: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    embedding: Optional[list[float]] = Field(default=None, description="Vector embedding")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ============================================================================
# Note Models
# ============================================================================


class NoteBase(BaseModel):
    """Base model for note data."""

    content_text: str = Field(..., description="Raw content of the note")
    content_type: ContentType = Field(default=ContentType.MARKDOWN)
    source_url: Optional[str] = Field(default=None, description="Source URL if applicable")


class NoteCreate(NoteBase):
    """Model for creating a new note."""

    user_id: Optional[UUID] = Field(
        default=UUID("00000000-0000-0000-0000-000000000001"),
        description="User ID (defaults to test user)",
    )


class Note(NoteBase):
    """Full note model with ID and metadata."""

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"from_attributes": True}



# ============================================================================
# Chunk Models (Hierarchical)
# ============================================================================


class ChunkLevel(str, Enum):
    """Level of the chunk in hierarchy."""

    PARENT = "parent"
    CHILD = "child"


class ChunkBase(BaseModel):
    """Base model for a document chunk."""

    content: str
    chunk_index: Optional[int] = None
    chunk_level: ChunkLevel = ChunkLevel.CHILD
    source_location: Optional[dict[str, Any]] = None


class ChunkCreate(ChunkBase):
    """Model for creating a chunk."""

    note_id: UUID
    parent_chunk_id: Optional[UUID] = None
    embedding: Optional[list[float]] = None


class Chunk(ChunkBase):
    """Full chunk model."""

    id: UUID
    note_id: UUID
    parent_chunk_id: Optional[UUID] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ============================================================================
# Proposition Models
# ============================================================================


class PropositionBase(BaseModel):
    """Base model for an atomic proposition."""

    content: str
    confidence: float = 0.0
    is_atomic: bool = True


class PropositionCreate(PropositionBase):
    """Model for creating a proposition."""

    note_id: UUID
    chunk_id: UUID


class Proposition(PropositionBase):
    """Full proposition model."""

    id: UUID
    note_id: UUID
    chunk_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


# ============================================================================
# Graph Operation Models
# ============================================================================


class Relationship(BaseModel):
    """Model for a relationship between concepts."""

    from_concept_id: str
    to_concept_id: str
    relationship_type: RelationshipType
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphOperation(BaseModel):
    """Model for a graph update operation."""

    operation_type: GraphOperationType
    concept: Optional[Concept] = None
    relationship: Optional[Relationship] = None
    reason: str = Field(default="", description="Explanation for the operation")


# ============================================================================
# Conflict Detection Models
# ============================================================================


class Conflict(BaseModel):
    """Model for a detected conflict between concepts."""

    new_concept_name: str
    decision: ConflictDecision
    confidence: float = Field(ge=0.0, le=1.0)
    matched_concept_id: Optional[str] = None
    reasoning: str
    merge_strategy: MergeStrategy
    updated_definition: Optional[str] = None


class SynthesisResult(BaseModel):
    """Result from the synthesis agent."""

    decisions: list[Conflict]


# ============================================================================
# API Request/Response Models
# ============================================================================


class IngestRequest(BaseModel):
    """Request model for note ingestion."""

    content: str = Field(..., description="Markdown/text content to ingest")
    source_url: Optional[str] = Field(default=None, description="Optional source URL")
    user_id: Optional[str] = Field(
        default="00000000-0000-0000-0000-000000000001",
        description="User ID for the note",
    )


class IngestResponse(BaseModel):
    """Response model for note ingestion."""

    note_id: str
    concepts_extracted: list[str] = Field(
        default_factory=list, description="IDs of extracted concepts"
    )
    concepts_created: int = Field(default=0, description="Number of new concepts created")
    relationships_created: int = Field(default=0, description="Number of relationships created")
    status: str = Field(default="completed")
    processing_time_ms: Optional[float] = None


class GraphResponse(BaseModel):
    """Response model for graph queries."""

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    total_concepts: int = Field(default=0)
    total_relationships: int = Field(default=0)


class ConceptResponse(BaseModel):
    """Response model for concept details."""

    concept: Concept
    related_notes: list[str] = Field(default_factory=list)
    proficiency_score: Optional[float] = None
    last_reviewed: Optional[datetime] = None


class HealthResponse(BaseModel):
    """Response model for health checks."""

    status: str
    postgres: dict[str, Any]
    neo4j: dict[str, Any]
    version: str = "0.1.0"


# ============================================================================
# Extraction Models (Agent Output)
# ============================================================================


class ExtractionResult(BaseModel):
    """Result from the extraction agent."""

    concepts: list[ConceptCreate]
    raw_response: Optional[str] = None
    model_used: str = "gemini-2.5-flash"
    processing_time_ms: Optional[float] = None
