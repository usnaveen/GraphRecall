# GraphRecall: Robust Document Chunking & RAG Architecture
## Comprehensive Implementation Guide for Educational Active-Recall Platform

**Version**: 1.1 | **Date**: February 2026 | **Author**: AI Architecture Review

---

## Executive Summary

This document proposes a production-ready document ingestion pipeline for GraphRecall that addresses the limitations of your current "naive" implementation. The strategy moves beyond character truncation to implement **semantic-aware hierarchical chunking, multimodal document parsing, and citation-grounded retrieval**.

**Key Improvements**:
- ✅ **Semantic Preservation**: Replace 100k character truncation with intelligent hierarchical chunking
- ✅ **Multimodal Support**: Handle PDFs, slides, images, diagrams, and code together
- ✅ **Citation Accuracy**: Track precise source locations (page numbers, sections, coordinates)
- ✅ **Learning Item Quality**: Generate diverse quiz/flashcard items from coherent semantic chunks
- ✅ **Proposition Modeling**: (Phase 3) Atomic fact extraction for fine-grained reasoning
- ✅ **Concept-Centric Generation**: Generate cards by aggregating propositions across the graph
- ✅ **Cost-Efficient**: Use Gemini Flash for bulk processing; cache embeddings strategically
- ✅ **Scalable**: LangGraph orchestration for parallel processing stages

---

## Part 1: System Architecture Overview

### 1.1 Updated Tech Stack (Additions)

```
Frontend:     React TypeScript (KEEP)
              ├─ File upload handler (stream to backend)
              └─ Citation UI renderer

Backend:      Python FastAPI (KEEP)
              ├─ Document Parsing Service (NEW) → LlamaParse/Unstructured.io
              ├─ Chunking Pipeline (NEW) → Semantic + Hierarchical + Proposition
              └─ Learning Item Generator (NEW) → Diverse card types

Orchestration: LangGraph StateGraph (KEEP)
              ├─ Parse → Chunk → Proposition Extract (Opt) → Embed → Extract Concepts → Generate Cards
              └─ Parallel batch stages for scale

Databases:    Neo4j (Concepts/Relationships) (KEEP)
              PostgreSQL (Notes/Chunks/Propositions/Metadata) (KEEP)
              Vector Store (NEW) → Weaviate/Pinecone or pgvector (local)

LLM:          Gemini 1.5 Flash (batching) + Pro (reasoning)
Embeddings:   Gemini Embeddings API or all-MiniLM-L6-v2 (local)
```

### 1.2 Ingestion Pipeline Architecture (Phased)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ USER UPLOAD (Any Format: PDF, PPTX, DOCX, Images, Markdown, etc.)      │
└────────────────────────┬────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: DOCUMENT PARSING (Backend Service) - Phase 1                   │
│                                                                           │
│ LlamaParse / Unstructured.io                                            │
│ ├─ Structure Extraction: Headers, sections, page breaks                 │
│ ├─ Multimodal Processing: Extract images, tables, diagrams              │
│ ├─ Layout Preservation: Markdown output with hierarchy                  │
│ ├─ Metadata Capture: Page numbers, slide numbers, coordinates           │
│ └─ Output: Clean markdown with embedded image references & JSON         │
└────────────────────────┬────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: HIERARCHICAL CHUNKING - Phase 1                                │
│                                                                           │
│ Input-Type Specific Strategies:                                         │
│                                                                           │
│ A) TEXTBOOKS / RESEARCH PAPERS (Hierarchical)                           │
│    Parse structure: [Chapter] → [Section] → [Subsection] → [Paragraph]  │
│    Parent Chunks: Full sections (context for generation)                │
│    Child Chunks: Paragraphs/topics (precise retrieval)                  │
│    Overlap: 20% to preserve context bridges                             │
│                                                                           │
│ B) LECTURE SLIDES (Semantic + Sequential)                               │
│    Structure: [Slide] → [Text Blocks] + [Images]                        │
│    Parent Chunks: Slide + speaker notes (if available)                  │
│    Child Chunks: Individual content blocks                              │
│    Semantic Merge: Adjacent slides with same topic                      │
│                                                                           │
│ C) LLM CHAT TRANSCRIPTS (Sequential Semantic)                           │
│    Structure: [Conversation Turn] → [Paired Message]                    │
│    Parent Chunks: Full exchange (user Q + AI response + follow-up)      │
│    Child Chunks: Individual turns                                       │
│    Semantic Merge: Multi-turn conversations on same topic               │
│                                                                           │
│ D) MARKDOWN NOTES (Structure-Preserving)                                │
│    Use `MarkdownHeaderTextSplitter` preserving hierarchy                 │
│    Parent: Sections under H2                                            │
│    Child: Subsections under H3/H4                                       │
│                                                                           │
│ E) CODE CONTENT (AST or Proposition-Based)                              │
│    Parse: Function/class definitions → Methods/properties               │
│    Proposition: Break into logical code chunks                          │
│    Parent: File/module                                                  │
│    Child: Function or class definition                                  │
│                                                                           │
│ OUTPUT: Hierarchical chunk tree with parent_id, source_location         │
└────────────────────────┬────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 2.5: PROPOSITION EXTRACTION (Optional) - Phase 3                  │
│ (For core theory sections, extract atomic facts)                        │
│                                                                           │
│ Input: Child Chunk + Parent Context                                     │
│ Action: Use LLM to decompose text into atomic declarative statements.   │
│ Output: List of Propositions linked to Source Chunk & Concept IDs.      │
│ Storage: `propositions` table & Neo4j edges backed by props.            │
└────────────────────────┬────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: SEMANTIC ENHANCEMENT (Optional, Per-Chunk) - Phase 2           │
│                                                                           │
│ For chunks > 256 tokens:                                                │
│ ├─ Vision Model: Caption images/diagrams                                │
│ ├─ Summary: 1-line abstraction of chunk meaning                         │
│ └─ Keyword Extraction: Top 3-5 concepts                                 │
│                                                                           │
│ Cost-Effective: Use Gemini Flash in batch mode                          │
└────────────────────────┬────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: METADATA ENRICHMENT - Phase 1                                  │
│                                                                           │
│ Per-chunk metadata:                                                     │
│ {                                                                        │
│   "chunk_id": "note_1_ch_2_para_3",                                     │
│   "parent_chunk_id": "note_1_ch_2",                                     │
│   "note_id": "1",                                                        │
│   "source_type": "pdf | slide | transcript | markdown | code",          │
│   "location": {                                                          │
│     "page_number": 42,                                                  │
│     "slide_number": 12,                                                 │
│     "timestamp": "1:23:45",  # For video transcripts                    │
│     "section_title": "3.2 Wave Functions",                              │
│     "hierarchy_path": ["Chapter 3", "Section 3.2"]                      │
│   },                                                                     │
│   "content_type": "text | image | table | code | proposition",          │
│   "images_referenced": ["img_1.png", "img_2.png"],  # For retrieval    │
│   "is_summary": false,                                                  │
│   "embedding_token_count": 248                                          │
│ }                                                                        │
└────────────────────────┬────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 5: EMBEDDING & VECTOR INDEXING - Phase 1                          │
│                                                                           │
│ ONLY embed child chunks (and later propositions):                       │
│ ├─ Model: Gemini Embeddings (768 dims) or all-MiniLM-L6-v2 (384 dims)  │
│ ├─ Batch: Process 100-1000 chunks per batch API call                   │
│ ├─ Storage: Vector store (pgvector/Chroma)                             │
│ ├─ Cache: Store in PostgreSQL for reuse (avoid re-embedding)            │
│ └─ Cost Savings: 70-80% fewer embeddings vs naive approach              │
│                                                                          │
│ Vector metadata (indexed for filtering):                                │
│   - source_type, page_number, section_title, content_type              │
│   - Enables: "Find code examples on page 15" queries                   │
└────────────────────────┬────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 6: CONCEPT EXTRACTION & RELATIONSHIP BUILDING (Neo4j) - Phase 2   │
│                                                                           │
│ Batch Processing via LangGraph:                                         │
│ 1. Group child chunks by parent (context preservation)                  │
│ 2. Extract concepts & relationship types via LLM                        │
│ 3. Create Neo4j nodes: Concept(name, definition, ...)                   │
│ 4. Create edges: Concept --[MENTIONED_IN_CHUNK]--> Chunk                │
│                  Concept --[PREREQUISITE_FOR]--> Concept               │
│                  Concept --[RELATED_TO]--> Concept                     │
│                  Concept --[SUPPORTED_BY]--> Proposition (Phase 3)      │
│                                                                          │
│ Chunk/Proposition backreference in Neo4j enables citation.              │
└────────────────────────┬────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ STAGE 7: LEARNING ITEM GENERATION - Phase 1 (Chunk) / Phase 3 (Prop)    │
│                                                                           │
│ A) Chunk-Based Generation (Phase 1):                                    │
│    - Generate Flashcards/MCQs directly from chunks during ingestion     │
│                                                                           │
│ B) Concept-Centric Generation (Phase 2/3):                              │
│    - Aggregates all propositions for a Concept across the graph         │
│    - Generates:                                                           │
│      * "Easy": Fact recall from single proposition                      │
│      * "Medium": Prerequisite linking (Concept A + B)                   │
│      * "Hard": Multi-hop reasoning chains                               │
│                                                                          │
│ Deduplication: Cluster similar items via semantic similarity.           │
│   - Cluster similar flashcards                                          │
│   - Keep highest-quality variant per cluster                            │
│   - Merge with existing items in DB                                     │
└─────────────────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ STORAGE LAYER (Parallel Writes)                                         │
│                                                                           │
│ PostgreSQL:                                                              │
│   - notes: (id, user_id, filename, original_file_type, upload_date)    │
│   - chunks: (id, note_id, parent_id, content, source_location, ...)    │
│   - chunk_metadata: (chunk_id, key, value) -- flexible schema            │
│   - embeddings: (chunk_id, embedding_vector, model_version)             │
│   - learning_items: (id, chunk_id, item_type, front, back, difficulty) │
│                                                                          │
│ Neo4j:                                                                   │
│   - (:Concept {name, definition, chunk_references: [chunk_ids]})        │
│   - (:Chunk {chunk_id, note_id, source_location_json})                  │
│   - (:LearningItem {item_id, item_type})                                │
│   - RELATIONSHIPS: [MENTIONED_IN], [PREREQUISITE], [RELATED], [NEXT]   │
│                                                                          │
│ Vector Store (Weaviate/Pinecone):                                       │
│   - Objects: {chunk_id, embedding, metadata: {type, page, section, ...}} │
│   - Indexes: semantic search + metadata filtering                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Part 2: Detailed Implementation Specifications

### 2.1 Chunking Algorithms by Content Type

#### Strategy A: Hierarchical Semantic Chunking (Textbooks, Papers)

```python
# Pseudocode
class HierarchicalSemanticChunker:
    def __init__(self, 
                 parent_chunk_size=1024,      # tokens
                 child_chunk_size=256,        # tokens
                 overlap_ratio=0.2,
                 model_name="text-embedding-3-small"):
        self.parent_size = parent_chunk_size
        self.child_size = child_chunk_size
        self.overlap = overlap_ratio
        self.embed_model = load_embeddings(model_name)
    
    def chunk(self, document: ParsedDocument) -> List[HierarchicalChunk]:
        """
        1. Extract document structure (headers, section markers)
        2. Split at structural boundaries first (chapters → sections)
        3. Create parent chunks (semantically coherent sections)
        4. Further split parents into child chunks
        5. Detect semantic boundaries within children (optional merge)
        6. Return hierarchy with parent_id references
        """
        # Step 1: Structure extraction (leveraging markdown from parser)
        hierarchy = extract_hierarchy(document.markdown)
        # e.g., [H1("Chapter 1"), H2("Section 1.1"), [paragraphs...]]
        
        # Step 2: Create parent chunks (full section with context)
        parent_chunks = []
        for section in hierarchy.sections:
            content = section.full_text()
            if len(tokenize(content)) > self.parent_size:
                # Split large sections recursively at subsection level
                subsection_chunks = []
                for subsection in section.subsections:
                    subsection_chunks.append(HierarchicalChunk(
                        id=f"{section.id}_sub_{idx}",
                        parent_id=section.id,
                        content=subsection.full_text(),
                        level="parent",
                        location={
                            "section": section.title,
                            "subsection": subsection.title,
                            "page": subsection.page_number
                        }
                    ))
                parent_chunks.extend(subsection_chunks)
            else:
                parent_chunks.append(HierarchicalChunk(
                    id=section.id,
                    parent_id=section.parent_id,
                    content=content,
                    level="parent",
                    location={"section": section.title, "page": section.start_page}
                ))
        
        # Step 3: Create child chunks (precise retrieval units)
        all_child_chunks = []
        for parent in parent_chunks:
            sentences = sentence_tokenize(parent.content)
            children = self._semantic_sentence_merge(
                sentences,
                target_size=self.child_size,
                overlap_pct=self.overlap
            )
            for i, child_content in enumerate(children):
                all_child_chunks.append(HierarchicalChunk(
                    id=f"{parent.id}_child_{i}",
                    parent_id=parent.id,
                    content=child_content,
                    level="child",
                    location=parent.location
                ))
        
        return all_child_chunks  # Parents stored separately with parent_id link
    
    def _semantic_sentence_merge(self, sentences, target_size, overlap_pct):
        """
        Merge adjacent sentences using embedding similarity.
        Stop merging when semantic distance threshold exceeded or size limit hit.
        """
        embeddings = self.embed_model.embed_batch(sentences)
        chunks = []
        current_chunk = []
        current_tokens = 0
        
        for i, (sentence, embedding) in enumerate(zip(sentences, embeddings)):
            sentence_tokens = len(tokenize(sentence))
            
            # Check semantic boundary with previous sentence
            if i > 0:
                prev_embedding = embeddings[i-1]
                similarity = cosine_similarity(embedding, prev_embedding)
                # If similarity drops below threshold, start new chunk
                if similarity < 0.7 and current_tokens > target_size * 0.5:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = [sentence]
                    current_tokens = sentence_tokens
                    continue
            
            # Add sentence if it fits
            if current_tokens + sentence_tokens <= target_size:
                current_chunk.append(sentence)
                current_tokens += sentence_tokens
            else:
                # Chunk full, save and start new
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                current_chunk = [sentence]
                current_tokens = sentence_tokens
        
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        
        return chunks
```

#### Strategy B: Proposition-Based Chunking (Code Content)

```python
# For code, use AST-based or proposition extraction
class PropositionBasedChunker:
    def chunk_code(self, code_text: str, language: str = "python") -> List[Chunk]:
        """
        Extract logical propositions from code:
        - Function/class definitions
        - Import statements
        - Logical code blocks (if/else, loops, etc.)
        """
        ast_tree = parse(code_text, language=language)
        propositions = []
        
        # Extract top-level definitions
        for node in ast_tree.body:
            if isinstance(node, (FunctionDef, ClassDef)):
                prop = {
                    "type": "definition",
                    "name": node.name,
                    "content": unparse(node),
                    "docstring": ast.get_docstring(node)
                }
                propositions.append(prop)
        
        # Group into chunks (~256-512 tokens each)
        chunks = []
        current_group = []
        current_tokens = 0
        
        for prop in propositions:
            tokens = len(tokenize(prop["content"]))
            if current_tokens + tokens > 512:
                chunks.append("\n\n".join([p["content"] for p in current_group]))
                current_group = [prop]
                current_tokens = tokens
            else:
                current_group.append(prop)
                current_tokens += tokens
        
        if current_group:
            chunks.append("\n\n".join([p["content"] for p in current_group]))
        
        return chunks
```

#### Strategy C: Slide Chunking (Lecture Slides)

```python
class SlideChunker:
    def chunk_slides(self, parsed_slides: List[Slide]) -> List[Chunk]:
        """
        Each slide = parent chunk.
        Content blocks, images, speaker notes = child chunks.
        Adjacent slides on same topic = semantic merge.
        """
        chunks = []
        slide_groups = self._group_semantically_similar_slides(parsed_slides)
        
        for group in slide_groups:
            # Create parent: full slide content
            parent_id = f"slide_group_{group.start_slide_idx}"
            parent_content = "\n\n".join([slide.full_text() for slide in group.slides])
            
            # Create children: individual content blocks
            for slide_idx, slide in enumerate(group.slides):
                for block_idx, block in enumerate(slide.content_blocks):
                    child_id = f"{parent_id}_slide_{slide_idx}_block_{block_idx}"
                    chunks.append(Chunk(
                        id=child_id,
                        parent_id=parent_id,
                        content=block.text,
                        metadata={
                            "slide_number": slide.slide_number,
                            "block_type": block.type,  # text, image, table, code
                            "has_image": block.image_ref is not None
                        }
                    ))
        
        return chunks
    
    def _group_semantically_similar_slides(self, slides: List[Slide]):
        """
        Merge adjacent slides if their topics are similar.
        Use topic modeling or title similarity.
        """
        groups = []
        current_group = [slides[0]]
        
        for i in range(1, len(slides)):
            prev_title_emb = embed(slides[i-1].title)
            curr_title_emb = embed(slides[i].title)
            similarity = cosine_similarity(prev_title_emb, curr_title_emb)
            
            if similarity > 0.7:  # Same topic
                current_group.append(slides[i])
            else:
                groups.append(SlideGroup(current_group))
                current_group = [slides[i]]
        
        if current_group:
            groups.append(SlideGroup(current_group))
        
        return groups
```

### 2.2 Metadata Schema (PostgreSQL)

```sql
-- Core notes table
CREATE TABLE notes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    original_filename VARCHAR(255),
    file_type VARCHAR(50),  -- pdf, pptx, docx, markdown, code, transcript
    ingestion_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_content TEXT,  -- For small files; use S3 for large
    parser_version VARCHAR(50),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Chunks with hierarchy and source tracking
CREATE TABLE chunks (
    id SERIAL PRIMARY KEY,
    note_id INTEGER NOT NULL,
    parent_chunk_id INTEGER,
    chunk_index INTEGER,  -- Position in parent's children
    content TEXT NOT NULL,
    
    -- Hierarchy & sourcing
    chunk_level VARCHAR(20),  -- 'parent', 'child', 'grandchild'
    source_location_type VARCHAR(50),  -- 'page', 'slide', 'timestamp', 'line'
    source_location_value VARCHAR(255),  -- '42', '12', '1:23:45', '100-120'
    section_title VARCHAR(255),  -- For citation: "3.2 Wave Functions"
    hierarchy_path JSON,  -- ["Chapter 3", "Section 3.2", "Subsection 3.2.1"]
    
    -- Content metadata
    content_type VARCHAR(50),  -- 'text', 'image', 'table', 'code', 'diagram'
    images_referenced JSON,  -- ["img_1.png", "img_2.png"]
    is_summary BOOLEAN DEFAULT FALSE,
    
    -- Embedding info
    embedding_id VARCHAR(255),  -- FK to embeddings table
    embedding_token_count INTEGER,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_chunk_id) REFERENCES chunks(id) ON DELETE SET NULL,
    INDEX idx_note_id (note_id),
    INDEX idx_parent_id (parent_chunk_id),
    UNIQUE KEY uk_chunk_id (id)
);

-- Flexible metadata tagging
CREATE TABLE chunk_metadata (
    id SERIAL PRIMARY KEY,
    chunk_id INTEGER NOT NULL,
    key VARCHAR(100),
    value TEXT,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE,
    INDEX idx_chunk_key (chunk_id, key)
);

-- Embeddings cache (avoids re-embedding)
CREATE TABLE embeddings (
    id SERIAL PRIMARY KEY,
    chunk_id INTEGER NOT NULL UNIQUE,
    embedding_vector VECTOR(768),  -- pgvector extension required
    model_name VARCHAR(100),  -- 'text-embedding-3-small', 'all-MiniLM-L6-v2'
    embedding_created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE,
    INDEX idx_chunk_id (chunk_id)
);

-- Learning items (flashcards, quizzes, etc.)
CREATE TABLE learning_items (
    id SERIAL PRIMARY KEY,
    chunk_id INTEGER,  -- Can be NULL for graph-derived items
    concept_id INTEGER,  -- FK to Neo4j concept (stored as string ID)
    user_id INTEGER NOT NULL,
    
    item_type VARCHAR(50),  -- 'flashcard', 'mcq', 'cloze', 'code_completion', 'diagram'
    front_content TEXT,  -- Question, term, code snippet
    back_content TEXT,   -- Answer, definition, expected output
    
    difficulty_level VARCHAR(20),  -- 'easy', 'medium', 'hard'
    is_deduped BOOLEAN DEFAULT FALSE,
    deduped_from_item_id INTEGER,  -- Points to merged-with item
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_chunk_id (chunk_id),
    INDEX idx_concept_id (concept_id)
);

-- Citation tracking for RAG responses
CREATE TABLE rag_citations (
    id SERIAL PRIMARY KEY,
    response_id VARCHAR(255),  -- Conversation/response UUID
    chunk_id INTEGER NOT NULL,
    source_note_id INTEGER NOT NULL,
    citation_rank INTEGER,  -- 1st most relevant, 2nd, etc.
    similarity_score FLOAT,
    retrieval_method VARCHAR(50),  -- 'semantic', 'keyword', 'graph', 'hybrid'
    FOREIGN KEY (chunk_id) REFERENCES chunks(id),
    FOREIGN KEY (source_note_id) REFERENCES notes(id),
    INDEX idx_response_id (response_id),
    INDEX idx_chunk_id (chunk_id)
);
```

### 2.3 Neo4j Schema (Concept Graph)

```cypher
-- Concept nodes: Store direct reference to source chunks
CREATE CONSTRAINT unique_concept_name IF NOT EXISTS
FOR (c:Concept) REQUIRE c.name IS UNIQUE;

CREATE (c:Concept {
    name: "Wave Function",
    definition: "A mathematical description of quantum mechanical system state.",
    synonyms: ["state function", "ψ(psi)"],
    chunk_references: ["chunk_42", "chunk_43"],  -- PostgreSQL chunk IDs
    source_note_ids: [1, 2],
    first_appearance: "page_15"
});

-- Chunk nodes: Store complete source metadata for citation
CREATE (ch:Chunk {
    chunk_id: "chunk_42",
    note_id: 1,
    source_location: {
        page: 15,
        section: "3.2 Wave Functions",
        hierarchy: ["Chapter 3", "Section 3.2"]
    },
    content_preview: "The wave function ψ is..."
});

-- Relationships
CREATE (c1:Concept {name: "Wave Function"})
    -[:MENTIONED_IN]->(ch:Chunk {chunk_id: "chunk_42"});

CREATE (c1:Concept {name: "Schrödinger Equation"})
    -[:PREREQUISITE_FOR]->(c2:Concept {name: "Wave Function"});

CREATE (c2:Concept {name: "Wave Function"})
    -[:RELATED_TO]->(c3:Concept {name: "Superposition"});

-- Queries for RAG
MATCH (c:Concept {name: "Wave Function"})-[:MENTIONED_IN]->(ch:Chunk)
RETURN c.definition, ch.chunk_id, ch.source_location;

-- Find prerequisites and related concepts
MATCH (c1:Concept)-[:PREREQUISITE_FOR*]->(target:Concept {name: "Wave Function"})
RETURN c1.name, c1.definition;
```

### 2.4 LangGraph Orchestration Workflow

```python
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from typing import TypedDict, List, Annotated
import operator

class IngestionState(TypedDict):
    """Shared state across workflow stages"""
    note_id: str
    file_path: str
    file_type: str
    
    # Parsing stage output
    parsed_document: dict  # Markdown + images + structure
    parsing_errors: List[str]
    
    # Chunking stage output
    chunks: List[dict]
    parent_chunks: List[dict]
    chunking_metrics: dict
    
    # Embedding stage output
    embeddings: List[dict]
    vector_store_ids: List[str]
    
    # Concept extraction
    concepts: List[dict]
    relationships: List[dict]
    
    # Learning items
    learning_items: List[dict]
    
    # Metadata for all stages
    metadata: dict

# Define stage functions
async def parse_document(state: IngestionState) -> IngestionState:
    """Stage 1: Parse document using LlamaParse"""
    from llama_parse import LlamaParse
    
    parser = LlamaParse(
        api_key="YOUR_KEY",
        result_type="markdown",  # or "json"
    )
    
    parsed = parser.load_data(file_path=state["file_path"])
    
    state["parsed_document"] = {
        "markdown": parsed[0].get_content(),  # Markdown with hierarchy
        "images": parsed[0].metadata.get("images", []),
        "tables": parsed[0].metadata.get("tables", []),
        "file_type": state["file_type"],
    }
    
    return state

async def chunk_document(state: IngestionState) -> IngestionState:
    """Stage 2: Hierarchical semantic chunking"""
    from llama_index.core.node_parser import HierarchicalNodeParser, SentenceSplitter
    
    chunker = HierarchicalNodeParser.from_defaults(
        chunk_sizes=[1024, 256],  # parent, child
        chunk_overlap=50,
    )
    
    nodes = chunker.get_nodes_from_documents([
        Document(text=state["parsed_document"]["markdown"])
    ])
    
    # Enrich with source location
    chunks = []
    for node in nodes:
        chunks.append({
            "id": node.id_,
            "content": node.get_content(),
            "metadata": {
                **node.metadata,
                "source_note_id": state["note_id"],
                "file_type": state["file_type"],
            },
            "parent_id": node.parent_id,
        })
    
    state["chunks"] = chunks
    state["chunking_metrics"] = {
        "total_chunks": len(chunks),
        "total_tokens": sum(len(c["content"].split()) for c in chunks)
    }
    
    return state

async def embed_chunks(state: IngestionState) -> IngestionState:
    """Stage 3: Embed child chunks (not parents)"""
    from langchain_community.embeddings import HuggingFaceEmbeddings
    # or from langchain_google_genai import GoogleGenerativeAIEmbeddings
    
    # Filter child chunks only (where parent_id is not None)
    child_chunks = [c for c in state["chunks"] if c["parent_id"]]
    
    embedder = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    # Batch embedding for efficiency
    embeddings = embedder.embed_documents(
        [c["content"] for c in child_chunks]
    )
    
    state["embeddings"] = [
        {"chunk_id": c["id"], "embedding": e}
        for c, e in zip(child_chunks, embeddings)
    ]
    
    # Store in vector DB
    # (pseudo-code; actual implementation depends on DB choice)
    for emb in state["embeddings"]:
        vector_store.add_document(
            id=emb["chunk_id"],
            embedding=emb["embedding"],
            metadata={"source_note_id": state["note_id"]}
        )
    
    return state

async def extract_concepts(state: IngestionState) -> IngestionState:
    """Stage 4: Extract concepts and relationships"""
    from gemini_api import GenAI  # pseudo-import
    
    client = GenAI(api_key="YOUR_KEY")
    
    # Group chunks by parent for context
    parent_groups = {}
    for chunk in state["chunks"]:
        parent_id = chunk.get("parent_id") or chunk["id"]
        if parent_id not in parent_groups:
            parent_groups[parent_id] = []
        parent_groups[parent_id].append(chunk)
    
    concepts = []
    relationships = []
    
    # Batch process parent groups
    for parent_id, child_chunks in parent_groups.items():
        context = "\n\n".join([c["content"] for c in child_chunks])
        
        prompt = f"""
        Extract concepts and relationships from this educational content:
        
        {context}
        
        Return JSON:
        {{
            "concepts": [
                {{"name": "...", "definition": "...", "synonyms": []}},
                ...
            ],
            "relationships": [
                {{"source": "...", "target": "...", "type": "prerequisite|related|mentioned"}},
                ...
            ]
        }}
        """
        
        response = client.models.generateContent(
            model="gemini-1.5-flash",
            contents=prompt
        )
        
        extracted = json.loads(response.text)
        
        # Attach chunk references
        for concept in extracted["concepts"]:
            concept["chunk_references"] = [c["id"] for c in child_chunks]
            concept["source_note_id"] = state["note_id"]
            concepts.append(concept)
        
        relationships.extend(extracted["relationships"])
    
    state["concepts"] = concepts
    state["relationships"] = relationships
    
    return state

async def generate_learning_items(state: IngestionState) -> IngestionState:
    """Stage 5: Generate diverse learning items"""
    from gemini_api import GenAI
    
    client = GenAI(api_key="YOUR_KEY")
    
    learning_items = []
    
    # Process each chunk
    for chunk in state["chunks"]:
        if not chunk.get("parent_id"):  # Skip parent chunks
            continue
        
        prompt = f"""
        Generate diverse learning items from this educational chunk:
        
        Content:
        {chunk["content"][:2000]}  # Limit to 2000 chars
        
        Generate 1-2 items per type:
        1. Flashcard (term/definition or question/answer)
        2. Multiple Choice Question (3-4 options, 1 correct)
        3. Fill-in-the-blank (cloze deletion)
        
        Return JSON array of items.
        """
        
        response = client.models.generateContent(
            model="gemini-1.5-flash",
            contents=prompt
        )
        
        items = json.loads(response.text)
        
        for item in items:
            item["chunk_id"] = chunk["id"]
            item["source_note_id"] = state["note_id"]
            learning_items.append(item)
    
    state["learning_items"] = learning_items
    
    return state

# Build workflow graph
workflow = StateGraph(IngestionState)

workflow.add_node("parse", parse_document)
workflow.add_node("chunk", chunk_document)
workflow.add_node("embed", embed_chunks)
workflow.add_node("extract_concepts", extract_concepts)
workflow.add_node("generate_items", generate_learning_items)
workflow.add_node("store", store_all_to_databases)  # Final persistence

workflow.add_edge(START, "parse")
workflow.add_edge("parse", "chunk")
workflow.add_edge("chunk", "embed")
workflow.add_edge("chunk", "extract_concepts")  # Parallel with embedding
workflow.add_edge("embed", "generate_items")
workflow.add_edge("extract_concepts", "store")  # Both complete
workflow.add_edge("generate_items", "store")
workflow.add_edge("store", END)

app = workflow.compile()

# Execute
result = await app.ainvoke(initial_state)
```

---

## Part 3: RAG Retrieval with Precise Citations

### 3.1 Hybrid Retriever (Semantic + Keyword + Graph)

```python
class HybridCitationRetriever:
    """Combines BM25, vector search, and Neo4j graph traversal"""
    
    def __init__(self, pg_conn, neo4j_conn, vector_store, bm25_index):
        self.pg = pg_conn
        self.neo4j = neo4j_conn
        self.vector_store = vector_store
        self.bm25 = bm25_index
    
    async def retrieve_with_citations(self, query: str, top_k: int = 5) -> List[RetrievalResult]:
        """
        Multi-stage retrieval:
        1. BM25 keyword matching
        2. Vector similarity on child chunks
        3. Graph expansion via Neo4j
        4. Recursive retrieval: child → parent
        5. Attach citation metadata
        """
        
        # Stage 1: Keyword matching
        bm25_results = self.bm25.retrieve(query, k=10)
        bm25_chunk_ids = [r.chunk_id for r in bm25_results]
        
        # Stage 2: Vector similarity (on child chunks only)
        query_embedding = self.embed_query(query)
        vector_results = self.vector_store.search(
            query_embedding,
            limit=10,
            filter={"has_parent": True}  # Filter for child chunks
        )
        vector_chunk_ids = [r["chunk_id"] for r in vector_results]
        
        # Stage 3: Graph expansion (find related concepts)
        query_concepts = self.extract_query_concepts(query)
        graph_related_chunks = []
        for concept in query_concepts:
            cypher = """
            MATCH (c:Concept {name: $concept_name})-[:MENTIONED_IN]->(ch:Chunk)
            RETURN ch.chunk_id as chunk_id
            """
            results = self.neo4j.run(cypher, concept_name=concept)
            graph_related_chunks.extend([r["chunk_id"] for r in results])
        
        # Combine and deduplicate
        all_chunk_ids = set(bm25_chunk_ids + vector_chunk_ids + graph_related_chunks)
        
        # Stage 4: Recursive retrieval (child → parent)
        final_chunks = []
        for chunk_id in all_chunk_ids:
            chunk_data = self.get_chunk_data(chunk_id)
            
            # If child, fetch parent for context
            if chunk_data["parent_id"]:
                parent_chunk = self.get_chunk_data(chunk_data["parent_id"])
                retrieval_result = RetrievalResult(
                    child_chunk_id=chunk_id,
                    parent_chunk_id=chunk_data["parent_id"],
                    child_content=chunk_data["content"],
                    parent_content=parent_chunk["content"],
                    citations=self.extract_citations(chunk_data, parent_chunk),
                    relevance_score=vector_results[vector_chunk_ids.index(chunk_id)]["score"]
                        if chunk_id in vector_chunk_ids else 0.5
                )
            else:
                retrieval_result = RetrievalResult(
                    chunk_id=chunk_id,
                    content=chunk_data["content"],
                    citations=self.extract_citations(chunk_data, None),
                    relevance_score=0.5
                )
            
            final_chunks.append(retrieval_result)
        
        # Rank and return top-k
        final_chunks.sort(key=lambda x: x.relevance_score, reverse=True)
        return final_chunks[:top_k]
    
    def extract_citations(self, chunk_data, parent_data=None):
        """Format citation info for UI"""
        source_info = chunk_data.get("source_location", {})
        
        citation = {
            "source_note_id": chunk_data["note_id"],
            "chunk_id": chunk_data["id"],
            "location": {
                "type": source_info.get("type"),  # "page", "slide", etc.
                "value": source_info.get("value"),  # "42", "Slide 12"
                "section": chunk_data.get("section_title"),
                "hierarchy": chunk_data.get("hierarchy_path"),
            },
            "citation_string": f"Page {source_info.get('value', '?')}, {chunk_data.get('section_title', 'Content')}"
        }
        
        return citation
    
    def embed_query(self, query: str):
        """Embed user query using same model as chunks"""
        return self.vector_store.embed(query)
    
    def extract_query_concepts(self, query: str) -> List[str]:
        """Extract key concepts from query using NER or simple keyword extraction"""
        # Pseudo-implementation
        return keyword_extract(query)
```

### 3.2 Citation Rendering in Chat UI

```typescript
// React component for displaying citations
interface Citation {
  source_note_id: string;
  chunk_id: string;
  location: {
    type: string;  // "page", "slide", "timestamp"
    value: string;
    section?: string;
    hierarchy?: string[];
  };
  citation_string: string;
}

function ResponseWithCitations({ answer, citations }: { answer: string; citations: Citation[] }) {
  return (
    <div className="response-container">
      <div className="answer-text">{answer}</div>
      
      <div className="citations-section">
        <h4>Sources</h4>
        {citations.map((cite, idx) => (
          <CitationBox key={idx} citation={cite} index={idx + 1} />
        ))}
      </div>
    </div>
  );
}

function CitationBox({ citation, index }: { citation: Citation; index: number }) {
  const handleClick = () => {
    // Navigate to source in user's knowledge base
    window.location.href = `/note/${citation.source_note_id}/chunk/${citation.chunk_id}`;
  };
  
  return (
    <div className="citation-box" onClick={handleClick} style={{ cursor: "pointer" }}>
      <span className="citation-number">[{index}]</span>
      <div className="citation-content">
        <p className="citation-string">{citation.citation_string}</p>
        {citation.location.hierarchy && (
          <p className="citation-path">
            {citation.location.hierarchy.join(" > ")}
          </p>
        )}
      </div>
    </div>
  );
}
```

---

## Part 4: Cost Analysis & Optimization

### 4.1 Cost Breakdown (for 1000-page textbook)

| Component | Method | Estimate | Notes |
|-----------|--------|----------|-------|
| **Parsing** | LlamaParse (Standard) | $3-5 | ~0.003-0.005 per page |
| **Chunking** | Local (CPU) | $0 | Runs on backend server |
| **Embedding (Child chunks only)** | Gemini Embeddings | ~$0.02 | ~4000 child chunks × $5 per 1M tokens |
| **LLM Concept Extraction** | Gemini 1.5 Flash | ~$0.50 | Batch 40 parent chunks per call |
| **Learning Item Generation** | Gemini 1.5 Flash | ~$1.00 | Generate 3-5 items per chunk |
| **Vector Store** | Weaviate (self-hosted) | $0 | Or ~$20-50/mo for cloud |
| **Neo4j Graph** | Neo4j Aura (free tier) or self-hosted | $0-50/mo | Free for <175k relationships |
| **PostgreSQL** | AWS RDS or self-hosted | $20-50/mo | Minimal data volume initially |
| **Total per textbook** | | **$4.50-7.00** | Scales to 1000s of documents |

### 4.2 Optimization Strategies

1. **Embed Child Chunks Only** (70-80% savings)
   - Parent chunks used for context, not retrieval
   - Reduces embedding volume significantly

2. **Batch Processing**
   - Group 50-100 chunks per LLM call (vision/extraction)
   - Batch embeddings in 1000-chunk loads
   - ~2-3 API calls vs thousands

3. **Cache Embeddings**
   - Store in PostgreSQL embeddings table
   - Skip re-embedding for unchanged content

4. **Use Gemini Flash for Bulk Operations**
   - $0.075 per 1M input tokens (vs $1+ for GPT-4)
   - 1M context window accommodates large sections
   - Reserve Pro for complex reasoning only

---

## Part 5: Implementation Roadmap

### Phase 1: MVP (Weeks 1-4)
- [ ] Integrate LlamaParse for PDF/PPTX parsing
- [ ] Implement hierarchical semantic chunking (textbooks + slides)
- [ ] Add to PostgreSQL schema
- [ ] Build basic embeddings pipeline

### Phase 2: Core RAG (Weeks 5-8)
- [ ] Implement hybrid retriever (BM25 + vector + graph)
- [ ] Add Neo4j concept extraction
- [ ] Build citation tracking & UI
- [ ] Test on 50-page sample documents

### Phase 3: Scale & Refinement (Weeks 9-12)
- [ ] Learning item generation diversification
- [ ] Deduplication pipeline
- [ ] Performance optimization & caching
- [ ] Multimodal handling (images, diagrams, code)

### Phase 4: Production Hardening (Weeks 13-16)
- [ ] Error handling & retries
- [ ] Monitoring & logging
- [ ] User feedback loop
- [ ] Documentation & testing

---

## Part 6: Key Metrics & Evaluation

### Retrieval Quality Metrics
- **Recall@5**: % of relevant chunks retrieved in top 5
- **Precision@5**: % of top 5 results that are relevant
- **Citation Accuracy**: % of citations that match user's ground truth
- **Lost in the Middle**: % of questions answered correctly from documents of various lengths

### Learning Item Quality
- **Diversity Index**: % of generated items covering distinct concepts
- **Deduplication Accuracy**: % of correctly merged similar items
- **User Engagement**: Attempt rate and accuracy on generated items

### System Performance
- **End-to-end Latency**: Time from upload → learning items available
- **Embedding Latency**: Time to embed 1000 chunks
- **Query Latency**: Time for RAG response + citations

---

## Conclusion & Recommendations

This architecture replaces your naive truncation approach with a production-grade RAG pipeline that:

1. ✅ **Preserves Semantics**: Hierarchical chunking respects document structure
2. ✅ **Handles Diversity**: Custom strategies for textbooks, slides, code, chat transcripts
3. ✅ **Enables Citations**: Every answer traced to specific source locations
4. ✅ **Generates Quality Learning Items**: Diverse, non-redundant flashcards, quizzes, diagrams
5. ✅ **Scales Cost-Effectively**: Strategic embedding placement, batch LLM processing
6. ✅ **Supports Multimodal**: Images, diagrams, tables extracted and embedded

**Recommended Next Step**: Begin with Phase 1 MVP using LlamaParse + hierarchical chunking on a sample 50-page textbook. Validate retrieval quality and citation accuracy before scaling to production.

---

**Document Version**: 1.0  
**Last Updated**: February 6, 2026  
**Prepared for**: GraphRecall Team
