"""Pydantic models for Feed, Active Recall, and Content Generation."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ============================================================================
# Feed Content Types
# ============================================================================


class FeedItemType(str, Enum):
    """Types of items that can appear in the feed."""

    TERM_CARD = "flashcard"  # Renamed for user-facing "Term Card"
    MCQ = "mcq"
    FILL_BLANK = "fill_blank"
    INFOGRAPHIC = "infographic"  # User uploaded
    MERMAID_DIAGRAM = "diagram"
    SCREENSHOT = "screenshot"  # User uploaded
    CONCEPT_SHOWCASE = "concept_showcase"
    CODE_CHALLENGE = "code_challenge"


class DifficultyLevel(str, Enum):
    """Difficulty level for spaced repetition."""

    AGAIN = "again"  # Complete blackout, wrong answer
    HARD = "hard"  # Correct but with difficulty
    GOOD = "good"  # Correct with some hesitation
    EASY = "easy"  # Perfect recall


# ============================================================================
# Term Card Models (Formerly Flashcards)
# ============================================================================


class TermCardBase(BaseModel):
    """Base term card model."""

    concept_id: str = Field(..., description="ID of the related concept")
    front: str = Field(..., description="Front of the card (question/term)")
    back: str = Field(..., description="Back of the card (answer/definition)")
    card_type: str = Field(default="basic", description="Type: basic, cloze, or image")


class TermCardCreate(TermCardBase):
    """Model for creating a term card."""

    user_id: str
    note_id: Optional[str] = None


class TermCard(TermCardBase):
    """Full term card model with metadata."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    note_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# Quiz Models
# ============================================================================


class MCQOption(BaseModel):
    """An option in a multiple choice question."""

    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    text: str
    is_correct: bool = False


class MCQQuestion(BaseModel):
    """Multiple choice question model."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    concept_id: str
    question: str
    options: list[MCQOption]
    explanation: str = Field(default="", description="Explanation shown after answering")
    difficulty: int = Field(default=5, ge=1, le=10)


class FillBlankQuestion(BaseModel):
    """Fill in the blank question model."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    concept_id: str
    sentence: str = Field(..., description="Sentence with _____ for blanks")
    answers: list[str] = Field(..., description="Correct answers for blanks")
    hint: Optional[str] = None
    difficulty: int = Field(default=5, ge=1, le=10)


class CodeChallengeQuestion(BaseModel):
    """Code completion or CLI command challenge."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    concept_id: str
    language: str  # sql, python, bash, docker, etc.
    instruction: str
    initial_code: Optional[str] = None
    solution_code: str
    explanation: str
    difficulty: int = Field(default=5, ge=1, le=10)


# ============================================================================
# User Upload Models (Screenshots, Infographics)
# ============================================================================


class UserUpload(BaseModel):
    """Model for user-uploaded content."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    upload_type: FeedItemType = Field(..., description="screenshot or infographic")
    file_url: str = Field(..., description="URL to the uploaded file")
    thumbnail_url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    linked_concepts: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserUploadCreate(BaseModel):
    """Model for creating a user upload."""

    user_id: str
    upload_type: FeedItemType
    file_url: str
    title: Optional[str] = None
    description: Optional[str] = None
    linked_concepts: list[str] = Field(default_factory=list)


# ============================================================================
# Spaced Repetition Models (SM-2 Algorithm)
# ============================================================================


class SM2Data(BaseModel):
    """SM-2 algorithm data for a concept/item."""

    item_id: str  # Can be concept_id, flashcard_id, etc.
    item_type: str  # "concept", "flashcard", "mcq"
    user_id: str

    # SM-2 parameters
    easiness_factor: float = Field(default=2.5, ge=1.3, description="E-Factor")
    interval: int = Field(default=1, ge=1, description="Days until next review")
    repetition: int = Field(default=0, ge=0, description="Number of successful reviews")

    # Tracking
    last_review: Optional[datetime] = None
    next_review: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_reviews: int = 0
    correct_streak: int = 0


class ReviewResult(BaseModel):
    """Result of a review session."""

    item_id: str
    item_type: str
    user_id: str
    difficulty: DifficultyLevel
    response_time_ms: Optional[int] = None
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# Feed Models
# ============================================================================


class FeedItem(BaseModel):
    """A single item in the user's feed."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    item_type: FeedItemType
    content: dict[str, Any] = Field(..., description="Type-specific content")
    concept_id: Optional[str] = None
    concept_name: Optional[str] = None
    domain: Optional[str] = None
    priority_score: float = 0.5

    # Spaced repetition data
    due_date: Optional[datetime] = None
    priority_score: float = Field(default=1.0, description="Higher = more urgent")

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeedResponse(BaseModel):
    """Response model for feed endpoint."""

    items: list[FeedItem]
    total_due_today: int
    completed_today: int
    daily_goal: int = 20
    streak_days: int
    domains: list[str] = Field(default_factory=list, description="Available domains to filter")


class FeedFilterRequest(BaseModel):
    """Request model for filtering feed."""

    user_id: str
    item_types: Optional[list[FeedItemType]] = None
    domains: Optional[list[str]] = None
    max_items: int = Field(default=20, le=50)
    include_overdue: bool = True
    difficulty_range: Optional[tuple[int, int]] = None  # (min, max)


# ============================================================================
# Human-in-the-Loop Review Models
# ============================================================================


class ConceptReviewItem(BaseModel):
    """A concept pending human review."""

    id: str
    name: str
    definition: str
    domain: str
    complexity_score: float
    confidence: float
    related_concepts: list[str]
    prerequisites: list[str]

    # Review-specific fields
    is_selected: bool = True  # Whether user wants to include this
    is_duplicate: bool = False  # AI detected as potential duplicate
    matched_existing_id: Optional[str] = None  # ID of existing concept if duplicate
    user_modified: bool = False  # Whether user has edited this


class ConceptReviewSession(BaseModel):
    """A session for reviewing extracted concepts."""

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    note_id: str
    original_content: str

    # Extracted concepts pending review
    concepts: list[ConceptReviewItem]
    conflicts: list[dict[str, Any]] = Field(default_factory=list)

    # Session state
    status: str = Field(default="pending")  # pending, approved, cancelled
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConceptReviewApproval(BaseModel):
    """User's approval/modification of extracted concepts."""

    session_id: str
    approved_concepts: list[ConceptReviewItem]
    removed_concept_ids: list[str] = Field(default_factory=list)
    added_concepts: list[ConceptReviewItem] = Field(default_factory=list)


# ============================================================================
# Mermaid Diagram Models
# ============================================================================


class MermaidDiagram(BaseModel):
    """A mermaid diagram generated from concepts."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    diagram_type: str = Field(default="flowchart", description="flowchart, mindmap, etc.")
    mermaid_code: str
    title: str
    source_concepts: list[str] = Field(..., description="Concept IDs used")
    source_note_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# GraphRAG Chat Models
# ============================================================================


class ChatMessage(BaseModel):
    """A message in the chat."""

    role: str = Field(..., description="user, assistant, or system")
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatRequest(BaseModel):
    """Request for chat endpoint."""

    user_id: str
    message: str
    conversation_history: list[ChatMessage] = Field(default_factory=list)
    include_sources: bool = True
    max_context_concepts: int = Field(default=10, le=20)
    conversation_id: Optional[str] = None
    source_ids: Optional[list[str]] = Field(
        default=None, 
        description="Optional list of note/concept IDs to scope retrieval to"
    )


class ChatResponse(BaseModel):
    """Response from chat endpoint."""

    response: str
    sources: list[dict[str, Any]] = Field(
        default_factory=list, description="Source notes/concepts"
    )
    related_concepts: list[dict[str, Any]] = Field(default_factory=list)
    suggested_actions: list[str] = Field(
        default_factory=list, description="Practice, view graph, etc."
    )


# ============================================================================
# Statistics and Progress Models
# ============================================================================



class DailyActivity(BaseModel):
    """Daily activity for heatmap."""

    date: str  # YYYY-MM-DD
    reviews_completed: int
    concepts_learned: int
    notes_added: int
    accuracy: float


class UserStats(BaseModel):
    """User learning statistics."""

    user_id: str
    total_concepts: int = 0
    total_notes: int = 0
    total_reviews: int = 0
    streak_days: int = 0
    accuracy_rate: float = 0.0  # 0-1

    # By domain
    domain_progress: dict[str, float] = Field(
        default_factory=dict, description="Domain -> mastery %"
    )

    # Spaced repetition stats
    due_today: int = 0
    completed_today: int = 0
    daily_goal: int = 20
    overdue: int = 0

    last_activity: Optional[datetime] = None
    
    # Activity history for heatmap
    daily_activity: list[DailyActivity] = Field(
        default_factory=list, description="Activity history for heatmap"
    )





# ============================================================================
# 3D Graph Visualization Models
# ============================================================================


class Graph3DNode(BaseModel):
    """A node for 3D graph visualization."""

    id: str
    name: str
    definition: str
    domain: str
    complexity_score: float
    mastery_level: float = Field(default=0.0, ge=0.0, le=1.0)

    # 3D positioning (optional, can be calculated client-side)
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None

    # Visual properties
    size: float = Field(default=1.0, description="Relative node size")
    color: Optional[str] = None  # Hex color based on domain/mastery


class Graph3DEdge(BaseModel):
    """An edge for 3D graph visualization."""

    id: str
    source: str
    target: str
    relationship_type: str
    strength: float = Field(default=1.0, ge=0.0, le=1.0)


class Graph3DResponse(BaseModel):
    """Response model for 3D graph data."""

    nodes: list[Graph3DNode]
    edges: list[Graph3DEdge]
    clusters: list[dict[str, Any]] = Field(
        default_factory=list, description="Domain clusters for grouping"
    )
    communities: list[dict[str, Any]] = Field(
        default_factory=list, description="Graph-based communities"
    )
    total_nodes: int
    total_edges: int

