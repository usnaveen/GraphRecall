# GraphRecall: 2-Day MVP Implementation Guide
## **Complete Code Snippets for Every Component**
### **From Zero to Working Product in 48 Hours**

---

## **📋 TABLE OF CONTENTS**

1. [MVP Scope](#mvp-scope)
2. [Prerequisites & Setup](#prerequisites-setup)
3. [Day 1: Backend Core](#day-1-backend-core)
4. [Day 2: Frontend & Integration](#day-2-frontend-integration)
5. [Testing & Deployment](#testing-deployment)
6. [Post-MVP Roadmap](#post-mvp-roadmap)

---

## **MVP SCOPE**

### **What We're Building (48 Hours)**

```
┌─────────────────────────────────────────────────────────┐
│                    GraphRecall MVP                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ✅ Upload markdown notes                               │
│  ✅ Extract concepts (GPT-4o-mini)                      │
│  ✅ Build knowledge graph (Neo4j)                       │
│  ✅ Auto-generate flashcards                           │
│  ✅ Daily review with spaced repetition                │
│  ✅ Track proficiency                                  │
│  ✅ Basic synthesis (auto-merge similar notes)         │
│  ✅ Simple graph visualization                         │
│                                                          │
│  ❌ NOT in MVP:                                        │
│  ❌ OCR, YouTube, Chat, GitHub                         │
│  ❌ Advanced synthesis with conflicts                  │
│  ❌ Dynamic resume                                     │
│  ❌ Web scraping                                       │
│  ❌ Authentication                                     │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### **Tech Stack (Minimal)**
- **Backend**: Python 3.11 + FastAPI + LangGraph 1.0
- **DB**: PostgreSQL + Neo4j (Docker)
- **AI**: OpenAI API (gpt-4o-mini + gpt-4o)
- **Frontend**: Next.js 14 + React + Tailwind
- **Deploy**: Local (Docker Compose)

---

## **PREREQUISITES & SETUP**

### **Hour 0: Environment Setup (30 minutes)**

```bash
# 1. Install dependencies (macOS/Linux)
brew install python@3.11 node docker

# Windows: Install from official sites
# - Python 3.11: https://www.python.org/downloads/
# - Node.js 20: https://nodejs.org/
# - Docker Desktop: https://www.docker.com/products/docker-desktop/

# 2. Get API Keys
# OpenAI: https://platform.openai.com/api-keys
# Create account → Create API key → Save it

# 3. Create project directory
mkdir graphrecall-mvp
cd graphrecall-mvp

# 4. Initialize git
git init
echo "# GraphRecall MVP" > README.md
git add README.md
git commit -m "Initial commit"
```

---

## **DAY 1: BACKEND CORE (12 hours)**

### **Hour 1-2: Project Structure & Docker Setup**

#### **1.1 Create Project Structure**

```bash
# Create backend
mkdir -p backend/{app/{agents,api,db,models,graphs},tests}
cd backend

# Create Python virtual environment
python3.11 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Create requirements.txt
cat > requirements.txt << 'EOF'
# Core
fastapi==0.115.0
uvicorn[standard]==0.34.0
pydantic==2.5.0
pydantic-settings==2.1.0
python-dotenv==1.0.0
python-multipart==0.0.6

# LangChain/LangGraph
langchain==1.0.0
langchain-core==1.0.0
langchain-openai==1.0.0
langgraph==1.0.7
langgraph-checkpoint-sqlite==3.0.3

# Databases
asyncpg==0.29.0
sqlalchemy[asyncio]==2.0.25
alembic==1.13.0
neo4j==5.15.0
aiosqlite==0.19.0

# Utilities
httpx==0.28.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4

# Document Processing
pymupdf==1.23.0
python-markdown==3.5.0
EOF

# Install
pip install -r requirements.txt
```

#### **1.2 Docker Compose for Databases**

```yaml
# In project root: docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:15
    container_name: graphrecall-postgres
    environment:
      POSTGRES_USER: graphrecall
      POSTGRES_PASSWORD: graphrecall123
      POSTGRES_DB: graphrecall
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U graphrecall"]
      interval: 5s
      timeout: 5s
      retries: 5

  neo4j:
    image: neo4j:5
    container_name: graphrecall-neo4j
    environment:
      NEO4J_AUTH: neo4j/graphrecall123
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_apoc_export_file_enabled: 'true'
      NEO4J_apoc_import_file_enabled: 'true'
    ports:
      - "7474:7474"  # HTTP
      - "7687:7687"  # Bolt
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    healthcheck:
      test: ["CMD-SHELL", "cypher-shell -u neo4j -p graphrecall123 'RETURN 1'"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
  neo4j_data:
  neo4j_logs:
```

```bash
# Start databases
docker-compose up -d

# Verify
docker ps  # Should show 2 containers running

# Test Neo4j: http://localhost:7474
# Login: neo4j / graphrecall123
```

#### **1.3 Environment Variables**

```bash
# backend/.env
OPENAI_API_KEY=sk-your-key-here

# Database
DATABASE_URL=postgresql+asyncpg://graphrecall:graphrecall123@localhost:5432/graphrecall
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=graphrecall123

# LangSmith (optional but recommended)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls-your-key-here
LANGCHAIN_PROJECT=graphrecall-mvp

# App
DEBUG=true
FRONTEND_URL=http://localhost:3000
```

---

### **Hour 3-4: Database Models & Connections**

#### **2.1 PostgreSQL Models**

```python
# backend/app/db/postgres.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Text, DateTime, Float, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
import uuid
from datetime import datetime
from typing import AsyncGenerator
import os

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, echo=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()

# === MODELS ===

class Note(Base):
    __tablename__ = "notes"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(100), nullable=False, default="mvp_user")
    title = Column(String(500))
    content = Column(Text, nullable=False)
    content_format = Column(String(50), default='markdown')
    graph_node_ids = Column(ARRAY(String), default=[])  # Concept IDs created
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ProficiencyScore(Base):
    __tablename__ = "proficiency_scores"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(100), nullable=False, default="mvp_user")
    concept_id = Column(String(100), nullable=False)  # Neo4j node ID
    score = Column(Float, default=0.1)  # 0.0 to 1.0
    confidence = Column(Float, default=0.5)
    last_reviewed = Column(DateTime)
    next_review_due = Column(DateTime)
    review_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class Flashcard(Base):
    __tablename__ = "flashcards"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(100), nullable=False, default="mvp_user")
    concept_id = Column(String(100))
    note_id = Column(UUID(as_uuid=True))
    
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    card_type = Column(String(50), default='cloze')
    
    # SM-2 Algorithm fields
    ease_factor = Column(Float, default=2.5)
    interval = Column(Integer, default=0)  # days
    repetitions = Column(Integer, default=0)
    next_review = Column(DateTime)
    last_review = Column(DateTime)
    
    times_reviewed = Column(Integer, default=0)
    times_correct = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)

class ReviewHistory(Base):
    __tablename__ = "review_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(100), nullable=False, default="mvp_user")
    flashcard_id = Column(UUID(as_uuid=True), nullable=False)
    quality = Column(Integer)  # 0-5 rating
    response_time_ms = Column(Integer)
    reviewed_at = Column(DateTime, default=datetime.utcnow)
    new_interval = Column(Integer)
    new_ease_factor = Column(Float)

# === DATABASE FUNCTIONS ===

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI"""
    async with async_session_maker() as session:
        yield session

async def init_db():
    """Create all tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ PostgreSQL tables created")

async def close_db():
    """Close database connections"""
    await engine.dispose()
```

#### **2.2 Neo4j Client**

```python
# backend/app/db/neo4j.py
from neo4j import AsyncGraphDatabase
from typing import List, Dict, Any
import os
import uuid

class Neo4jClient:
    def __init__(self):
        self.uri = os.getenv("NEO4J_URI")
        self.user = os.getenv("NEO4J_USER")
        self.password = os.getenv("NEO4J_PASSWORD")
        self.driver = AsyncGraphDatabase.driver(
            self.uri,
            auth=(self.user, self.password)
        )
    
    async def close(self):
        await self.driver.close()
    
    async def run_query(self, query: str, parameters: Dict[str, Any] = None) -> List[Dict]:
        """Execute Cypher query"""
        async with self.driver.session() as session:
            result = await session.run(query, parameters or {})
            return await result.data()
    
    async def create_concept(
        self,
        name: str,
        description: str,
        note_id: str,
        user_id: str = "mvp_user"
    ) -> str:
        """Create or merge a concept node"""
        concept_id = str(uuid.uuid4())
        
        query = """
        MERGE (c:Concept {name: $name, user_id: $user_id})
        ON CREATE SET 
            c.id = $id,
            c.description = $description,
            c.created_at = datetime(),
            c.complexity_score = 0.5
        ON MATCH SET
            c.description = $description,
            c.updated_at = datetime()
        
        WITH c
        MERGE (n:NoteSource {id: $note_id})
        MERGE (n)-[:EXPLAINS {relevance: 0.9}]->(c)
        
        RETURN c.id as concept_id
        """
        
        result = await self.run_query(query, {
            "id": concept_id,
            "name": name,
            "description": description,
            "note_id": note_id,
            "user_id": user_id
        })
        
        return result[0]["concept_id"] if result else concept_id
    
    async def create_relationship(
        self,
        from_concept: str,
        to_concept: str,
        rel_type: str = "RELATED_TO",
        strength: float = 0.5
    ):
        """Create relationship between concepts"""
        query = f"""
        MATCH (c1:Concept {{id: $from_id}})
        MATCH (c2:Concept {{id: $to_id}})
        MERGE (c1)-[r:{rel_type}]->(c2)
        SET r.strength = $strength
        RETURN r
        """
        
        await self.run_query(query, {
            "from_id": from_concept,
            "to_id": to_concept,
            "strength": strength
        })
    
    async def find_similar_concepts(
        self,
        concept_name: str,
        user_id: str = "mvp_user",
        limit: int = 5
    ) -> List[Dict]:
        """Find concepts with similar names (simple text match)"""
        query = """
        MATCH (c:Concept {user_id: $user_id})
        WHERE c.name CONTAINS $search OR $search CONTAINS c.name
        RETURN c.id as id, c.name as name, c.description as description
        LIMIT $limit
        """
        
        return await self.run_query(query, {
            "user_id": user_id,
            "search": concept_name.lower(),
            "limit": limit
        })
    
    async def get_all_concepts(self, user_id: str = "mvp_user") -> List[Dict]:
        """Get all concepts for visualization"""
        query = """
        MATCH (c:Concept {user_id: $user_id})
        OPTIONAL MATCH (c)-[r]->(related:Concept)
        RETURN c, collect(DISTINCT related) as related, collect(DISTINCT r) as relationships
        """
        
        return await self.run_query(query, {"user_id": user_id})

# Global instance
neo4j_client = Neo4jClient()

async def get_neo4j():
    """Dependency for FastAPI"""
    return neo4j_client
```

---

### **Hour 5-6: LangGraph Agents - Ingestion**

#### **3.1 State Definitions**

```python
# backend/app/models/states.py
from typing import TypedDict, List, Optional, Literal
from typing_extensions import TypedDict as ExtTypedDict

class IngestionState(ExtTypedDict):
    """State for note ingestion workflow"""
    # Input
    user_id: str
    note_id: Optional[str]
    raw_content: str
    title: Optional[str]
    
    # Processing
    extracted_concepts: List[dict]
    related_concepts: List[dict]
    
    # Synthesis
    needs_synthesis: bool
    synthesis_completed: bool
    
    # Output
    created_concept_ids: List[str]
    final_note_id: Optional[str]
    error: Optional[str]
```

#### **3.2 Ingestion Agent**

```python
# backend/app/agents/ingestion.py
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.models.states import IngestionState
from app.db.postgres import async_session_maker, Note
from app.db.neo4j import neo4j_client
import json
import uuid
from datetime import datetime

# Initialize LLM
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)

async def extract_concepts_node(state: IngestionState) -> dict:
    """Extract concepts from note content"""
    
    prompt = f"""You are a concept extraction expert. Extract key concepts from this note.

Content:
{state['raw_content'][:3000]}

Instructions:
1. Focus on technical terms, theories, algorithms, or core ideas
2. Extract 3-7 concepts maximum
3. Each concept needs a name and brief description
4. Avoid generic terms like "introduction" or "overview"

Return ONLY valid JSON (no markdown, no extra text):
{{
    "concepts": [
        {{"name": "Concept Name", "description": "Brief description"}},
        ...
    ]
}}
"""
    
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        
        # Parse JSON from response
        content = response.content.strip()
        if content.startswith("```json"):
            content = content.split("```json")[1].split("```")[0].strip()
        elif content.startswith("```"):
            content = content.split("```")[1].split("```")[0].strip()
        
        data = json.loads(content)
        concepts = data.get("concepts", [])
        
        print(f"✅ Extracted {len(concepts)} concepts")
        return {"extracted_concepts": concepts}
        
    except Exception as e:
        print(f"❌ Concept extraction failed: {e}")
        return {"extracted_concepts": [], "error": str(e)}

async def find_related_node(state: IngestionState) -> dict:
    """Find related existing concepts"""
    
    related = []
    
    for concept in state["extracted_concepts"]:
        similar = await neo4j_client.find_similar_concepts(
            concept["name"],
            user_id=state["user_id"]
        )
        related.extend(similar)
    
    # Deduplicate
    seen = set()
    unique_related = []
    for r in related:
        if r["id"] not in seen:
            seen.add(r["id"])
            unique_related.append(r)
    
    needs_synthesis = len(unique_related) > 0
    
    print(f"📊 Found {len(unique_related)} related concepts")
    return {
        "related_concepts": unique_related,
        "needs_synthesis": needs_synthesis
    }

async def store_note_node(state: IngestionState) -> dict:
    """Store note in PostgreSQL"""
    
    note_id = state.get("note_id") or str(uuid.uuid4())
    
    async with async_session_maker() as session:
        note = Note(
            id=note_id,
            user_id=state["user_id"],
            title=state.get("title") or "Untitled Note",
            content=state["raw_content"],
            content_format="markdown",
            created_at=datetime.utcnow()
        )
        session.add(note)
        await session.commit()
    
    print(f"💾 Note saved: {note_id}")
    return {"final_note_id": note_id, "note_id": note_id}

async def create_concepts_node(state: IngestionState) -> dict:
    """Create concept nodes in Neo4j"""
    
    concept_ids = []
    note_id = state.get("note_id") or state.get("final_note_id")
    
    for concept in state["extracted_concepts"]:
        concept_id = await neo4j_client.create_concept(
            name=concept["name"],
            description=concept.get("description", ""),
            note_id=note_id,
            user_id=state["user_id"]
        )
        concept_ids.append(concept_id)
    
    # Create relationships between concepts in same note
    for i, concept_id in enumerate(concept_ids):
        for other_id in concept_ids[i+1:]:
            await neo4j_client.create_relationship(
                concept_id,
                other_id,
                rel_type="RELATED_TO",
                strength=0.6
            )
    
    # Update note with concept IDs
    async with async_session_maker() as session:
        result = await session.execute(
            "UPDATE notes SET graph_node_ids = :ids WHERE id = :note_id",
            {"ids": concept_ids, "note_id": note_id}
        )
        await session.commit()
    
    print(f"🔗 Created {len(concept_ids)} concept nodes")
    return {"created_concept_ids": concept_ids}

async def simple_synthesis_node(state: IngestionState) -> dict:
    """Simple synthesis: just create relationships to existing concepts"""
    
    # For MVP, we'll just link new concepts to related ones
    # Advanced synthesis comes in Phase 2
    
    new_concept_ids = state.get("created_concept_ids", [])
    related = state.get("related_concepts", [])
    
    for new_id in new_concept_ids:
        for related_concept in related[:3]:  # Link to top 3 related
            await neo4j_client.create_relationship(
                new_id,
                related_concept["id"],
                rel_type="RELATED_TO",
                strength=0.7
            )
    
    print(f"🔀 Linked to {len(related)} existing concepts")
    return {"synthesis_completed": True}
```

#### **3.3 Build Ingestion Graph**

```python
# backend/app/graphs/ingestion.py
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from app.models.states import IngestionState
from app.agents.ingestion import (
    extract_concepts_node,
    find_related_node,
    store_note_node,
    create_concepts_node,
    simple_synthesis_node
)

def create_ingestion_graph():
    """Build the ingestion workflow"""
    
    # Create graph
    builder = StateGraph(IngestionState)
    
    # Add nodes
    builder.add_node("extract_concepts", extract_concepts_node)
    builder.add_node("find_related", find_related_node)
    builder.add_node("store_note", store_note_node)
    builder.add_node("create_concepts", create_concepts_node)
    builder.add_node("synthesize", simple_synthesis_node)
    
    # Define flow
    builder.add_edge(START, "extract_concepts")
    builder.add_edge("extract_concepts", "store_note")
    builder.add_edge("store_note", "find_related")
    builder.add_edge("find_related", "create_concepts")
    builder.add_edge("create_concepts", "synthesize")
    builder.add_edge("synthesize", END)
    
    # Add checkpointer
    checkpointer = SqliteSaver.from_conn_string("checkpoints.db")
    
    return builder.compile(checkpointer=checkpointer)

# Global instance
ingestion_graph = create_ingestion_graph()
```

---

### **Hour 7-8: Flashcard Generation Agent**

```python
# backend/app/agents/flashcard_gen.py
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from app.db.postgres import async_session_maker, Flashcard, ProficiencyScore
from datetime import datetime, timedelta
import json
import uuid

llm_flashcard = ChatOpenAI(model="gpt-4o", temperature=0.4)

async def generate_flashcards_for_note(
    note_id: str,
    note_content: str,
    concepts: List[dict],
    user_id: str = "mvp_user"
) -> List[str]:
    """Generate flashcards from a note"""
    
    prompt = f"""Generate flashcards from this note.

Content:
{note_content[:2000]}

Key concepts:
{', '.join([c['name'] for c in concepts])}

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
        }},
        ...
    ]
}}
"""
    
    try:
        response = await llm_flashcard.ainvoke([HumanMessage(content=prompt)])
        
        content = response.content.strip()
        if content.startswith("```json"):
            content = content.split("```json")[1].split("```")[0].strip()
        elif content.startswith("```"):
            content = content.split("```")[1].split("```")[0].strip()
        
        data = json.loads(content)
        flashcards = data.get("flashcards", [])
        
        # Store flashcards
        card_ids = []
        async with async_session_maker() as session:
            for card in flashcards:
                # Find matching concept
                concept_id = None
                for c in concepts:
                    if c["name"].lower() in card.get("concept", "").lower():
                        concept_id = c.get("id")
                        break
                
                flashcard = Flashcard(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    concept_id=concept_id,
                    note_id=note_id,
                    question=card["question"],
                    answer=card["answer"],
                    card_type="cloze",
                    next_review=datetime.utcnow() + timedelta(days=1)
                )
                session.add(flashcard)
                card_ids.append(str(flashcard.id))
                
                # Initialize proficiency if concept exists
                if concept_id:
                    proficiency = ProficiencyScore(
                        user_id=user_id,
                        concept_id=concept_id,
                        score=0.1,
                        next_review_due=datetime.utcnow() + timedelta(days=1)
                    )
                    session.add(proficiency)
            
            await session.commit()
        
        print(f"📇 Generated {len(card_ids)} flashcards")
        return card_ids
        
    except Exception as e:
        print(f"❌ Flashcard generation failed: {e}")
        return []
```

---

### **Hour 9-10: Review Agent with Spaced Repetition**

```python
# backend/app/agents/review.py
from app.db.postgres import async_session_maker, Flashcard, ProficiencyScore, ReviewHistory
from sqlalchemy import select, and_, or_
from datetime import datetime, timedelta
import random

async def get_due_flashcards(user_id: str = "mvp_user", limit: int = 20) -> List[dict]:
    """Get flashcards due for review"""
    
    async with async_session_maker() as session:
        # Get cards due today
        query = select(Flashcard).where(
            and_(
                Flashcard.user_id == user_id,
                or_(
                    Flashcard.next_review <= datetime.utcnow(),
                    Flashcard.next_review.is_(None)
                )
            )
        ).limit(limit)
        
        result = await session.execute(query)
        flashcards = result.scalars().all()
        
        # Convert to dict
        cards = []
        for card in flashcards:
            cards.append({
                "id": str(card.id),
                "question": card.question,
                "answer": card.answer,
                "concept_id": card.concept_id,
                "times_reviewed": card.times_reviewed,
                "times_correct": card.times_correct
            })
        
        return cards

async def update_flashcard_srs(
    flashcard_id: str,
    quality: int,  # 0-5 rating
    response_time_ms: int,
    user_id: str = "mvp_user"
):
    """Update flashcard using SM-2 algorithm"""
    
    async with async_session_maker() as session:
        # Get flashcard
        result = await session.execute(
            select(Flashcard).where(Flashcard.id == flashcard_id)
        )
        card = result.scalar_one()
        
        # SM-2 Algorithm
        if quality >= 3:  # Correct
            if card.repetitions == 0:
                card.interval = 1
            elif card.repetitions == 1:
                card.interval = 6
            else:
                card.interval = int(card.interval * card.ease_factor)
            
            card.repetitions += 1
            card.times_correct += 1
        else:  # Incorrect
            card.repetitions = 0
            card.interval = 1
        
        # Update ease factor
        card.ease_factor = max(
            1.3,
            card.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        )
        
        # Set next review
        card.next_review = datetime.utcnow() + timedelta(days=card.interval)
        card.last_review = datetime.utcnow()
        card.times_reviewed += 1
        
        # Save review history
        history = ReviewHistory(
            user_id=user_id,
            flashcard_id=flashcard_id,
            quality=quality,
            response_time_ms=response_time_ms,
            new_interval=card.interval,
            new_ease_factor=card.ease_factor
        )
        session.add(history)
        
        # Update proficiency if concept exists
        if card.concept_id:
            prof_result = await session.execute(
                select(ProficiencyScore).where(
                    and_(
                        ProficiencyScore.user_id == user_id,
                        ProficiencyScore.concept_id == card.concept_id
                    )
                )
            )
            proficiency = prof_result.scalar_one_or_none()
            
            if proficiency:
                # Update proficiency score (exponential moving average)
                new_score = quality / 5.0
                proficiency.score = (proficiency.score * 0.7) + (new_score * 0.3)
                proficiency.last_reviewed = datetime.utcnow()
                proficiency.next_review_due = datetime.utcnow() + timedelta(days=card.interval)
                proficiency.review_count += 1
        
        await session.commit()
        
        return {
            "next_review": card.next_review.isoformat(),
            "interval": card.interval,
            "ease_factor": card.ease_factor
        }
```

---

### **Hour 11-12: FastAPI Application**

```python
# backend/app/main.py
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import List, Optional
import uuid

from app.db.postgres import init_db, close_db, get_db
from app.db.neo4j import neo4j_client, get_neo4j
from app.graphs.ingestion import ingestion_graph
from app.agents.flashcard_gen import generate_flashcards_for_note
from app.agents.review import get_due_flashcards, update_flashcard_srs

# === LIFECYCLE ===

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown"""
    # Startup
    print("🚀 Starting GraphRecall MVP...")
    await init_db()
    print("✅ Databases ready")
    
    yield
    
    # Shutdown
    print("👋 Shutting down...")
    await close_db()
    await neo4j_client.close()

app = FastAPI(
    title="GraphRecall MVP API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === MODELS ===

class NoteIngest(BaseModel):
    content: str
    title: Optional[str] = "Untitled Note"

class NoteResponse(BaseModel):
    note_id: str
    concepts: List[dict]
    flashcards: List[str]

class ReviewResponse(BaseModel):
    flashcard_id: str
    quality: int
    response_time_ms: int

# === ENDPOINTS ===

@app.get("/")
async def root():
    return {"message": "GraphRecall MVP API", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy", "database": "connected"}

@app.post("/api/notes/ingest", response_model=NoteResponse)
async def ingest_note(data: NoteIngest):
    """Ingest a new note"""
    
    thread_id = str(uuid.uuid4())
    note_id = str(uuid.uuid4())
    
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state = {
        "user_id": "mvp_user",
        "note_id": note_id,
        "raw_content": data.content,
        "title": data.title,
        "extracted_concepts": [],
        "related_concepts": [],
        "needs_synthesis": False,
        "synthesis_completed": False,
        "created_concept_ids": []
    }
    
    try:
        # Run ingestion graph
        result = await ingestion_graph.ainvoke(initial_state, config)
        
        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])
        
        # Generate flashcards
        flashcard_ids = await generate_flashcards_for_note(
            note_id=result["final_note_id"],
            note_content=data.content,
            concepts=[
                {"name": c["name"], "id": cid}
                for c, cid in zip(
                    result["extracted_concepts"],
                    result["created_concept_ids"]
                )
            ]
        )
        
        return NoteResponse(
            note_id=result["final_note_id"],
            concepts=result["extracted_concepts"],
            flashcards=flashcard_ids
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/review/due")
async def get_review_queue():
    """Get flashcards due for review"""
    
    cards = await get_due_flashcards(user_id="mvp_user", limit=20)
    
    return {
        "total": len(cards),
        "cards": cards
    }

@app.post("/api/review/submit")
async def submit_review(data: ReviewResponse):
    """Submit flashcard review"""
    
    result = await update_flashcard_srs(
        flashcard_id=data.flashcard_id,
        quality=data.quality,
        response_time_ms=data.response_time_ms
    )
    
    return {
        "success": True,
        "next_review": result["next_review"],
        "interval_days": result["interval"]
    }

@app.get("/api/graph")
async def get_graph():
    """Get knowledge graph for visualization"""
    
    concepts = await neo4j_client.get_all_concepts(user_id="mvp_user")
    
    # Format for frontend
    nodes = []
    edges = []
    
    for record in concepts:
        concept = record["c"]
        nodes.append({
            "id": concept["id"],
            "label": concept["name"],
            "description": concept.get("description", "")
        })
        
        # Extract relationships
        relationships = record.get("relationships", [])
        for rel in relationships:
            if rel:
                edges.append({
                    "source": concept["id"],
                    "target": rel.end_node["id"],
                    "type": rel.type
                })
    
    return {
        "nodes": nodes,
        "edges": edges
    }

# === RUN ===

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
```

#### **Test the Backend**

```bash
# Run the server
cd backend
source venv/bin/activate
python -m app.main

# Test in another terminal
curl http://localhost:8000/health

# Test ingestion
curl -X POST http://localhost:8000/api/notes/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "content": "# Gradient Descent\n\nGradient descent is an optimization algorithm used to minimize a function by iteratively moving in the direction of steepest descent.",
    "title": "Gradient Descent Notes"
  }'

# Should return: note_id, concepts, flashcards
```

---

## **DAY 2: FRONTEND & INTEGRATION (12 hours)**

### **Hour 13-14: Next.js Setup**

```bash
# From project root
npx create-next-app@latest frontend --typescript --tailwind --app --no-src-dir

cd frontend

# Install additional dependencies
npm install axios react-query @tanstack/react-query lucide-react

# Install shadcn/ui
npx shadcn-ui@latest init

# Install components
npx shadcn-ui@latest add button card input textarea
```

#### **Configure API Client**

```typescript
// frontend/lib/api.ts
import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// === API Functions ===

export interface Note {
  note_id: string;
  concepts: Array<{name: string; description: string}>;
  flashcards: string[];
}

export interface Flashcard {
  id: string;
  question: string;
  answer: string;
  concept_id?: string;
  times_reviewed: number;
  times_correct: number;
}

export const notesApi = {
  ingest: async (content: string, title: string): Promise<Note> => {
    const response = await api.post('/api/notes/ingest', { content, title });
    return response.data;
  },
};

export const reviewApi = {
  getDue: async (): Promise<{total: number; cards: Flashcard[]}> => {
    const response = await api.get('/api/review/due');
    return response.data;
  },
  
  submit: async (flashcardId: string, quality: number, timeMs: number) => {
    const response = await api.post('/api/review/submit', {
      flashcard_id: flashcardId,
      quality,
      response_time_ms: timeMs,
    });
    return response.data;
  },
};

export const graphApi = {
  get: async (): Promise<{nodes: any[]; edges: any[]}> => {
    const response = await api.get('/api/graph');
    return response.data;
  },
};
```

---

### **Hour 15-16: Note Ingestion Page**

```typescript
// frontend/app/ingest/page.tsx
'use client';

import { useState } from 'react';
import { notesApi } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Card } from '@/components/ui/card';
import { Loader2, CheckCircle } from 'lucide-react';

export default function IngestPage() {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setResult(null);

    try {
      const data = await notesApi.ingest(content, title || 'Untitled Note');
      setResult(data);
      setContent('');
      setTitle('');
    } catch (error) {
      console.error('Ingestion failed:', error);
      alert('Failed to ingest note');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container mx-auto px-4 py-8 max-w-4xl">
      <h1 className="text-3xl font-bold mb-6">Add New Note</h1>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium mb-2">Title</label>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Note title (optional)"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-2">Content (Markdown)</label>
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="# Your Notes Here&#10;&#10;Write your notes in markdown..."
            rows={15}
            required
          />
        </div>

        <Button type="submit" disabled={loading || !content}>
          {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {loading ? 'Processing...' : 'Ingest Note'}
        </Button>
      </form>

      {result && (
        <Card className="mt-8 p-6 bg-green-50">
          <div className="flex items-center gap-2 mb-4">
            <CheckCircle className="text-green-600" />
            <h2 className="text-xl font-semibold">Note Processed!</h2>
          </div>

          <div className="space-y-4">
            <div>
              <p className="font-medium">Concepts Extracted:</p>
              <ul className="list-disc list-inside mt-2">
                {result.concepts.map((c: any, i: number) => (
                  <li key={i} className="text-sm">
                    <strong>{c.name}</strong>: {c.description}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <p className="font-medium">Flashcards Generated: {result.flashcards.length}</p>
            </div>

            <Button onClick={() => (window.location.href = '/review')}>
              Start Reviewing →
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}
```

---

### **Hour 17-18: Review Page**

```typescript
// frontend/app/review/page.tsx
'use client';

import { useState, useEffect } from 'react';
import { reviewApi } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Loader2, CheckCircle, XCircle } from 'lucide-react';

interface Flashcard {
  id: string;
  question: string;
  answer: string;
  times_reviewed: number;
  times_correct: number;
}

export default function ReviewPage() {
  const [cards, setCards] = useState<Flashcard[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [showAnswer, setShowAnswer] = useState(false);
  const [loading, setLoading] = useState(true);
  const [startTime, setStartTime] = useState(Date.now());
  const [stats, setStats] = useState({ correct: 0, total: 0 });

  useEffect(() => {
    loadCards();
  }, []);

  const loadCards = async () => {
    try {
      const data = await reviewApi.getDue();
      setCards(data.cards);
      setLoading(false);
      setStartTime(Date.now());
    } catch (error) {
      console.error('Failed to load cards:', error);
      setLoading(false);
    }
  };

  const handleResponse = async (quality: number) => {
    const timeMs = Date.now() - startTime;
    const currentCard = cards[currentIndex];

    try {
      await reviewApi.submit(currentCard.id, quality, timeMs);
      
      // Update stats
      if (quality >= 3) {
        setStats(s => ({ correct: s.correct + 1, total: s.total + 1 }));
      } else {
        setStats(s => ({ ...s, total: s.total + 1 }));
      }

      // Move to next card
      if (currentIndex < cards.length - 1) {
        setCurrentIndex(currentIndex + 1);
        setShowAnswer(false);
        setStartTime(Date.now());
      } else {
        // Session complete
        alert(`Session Complete!\nScore: ${stats.correct + (quality >= 3 ? 1 : 0)}/${stats.total + 1}`);
      }
    } catch (error) {
      console.error('Failed to submit review:', error);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (cards.length === 0) {
    return (
      <div className="container mx-auto px-4 py-16 text-center">
        <h1 className="text-2xl font-bold mb-4">No Cards Due</h1>
        <p className="text-gray-600 mb-8">Come back tomorrow or add more notes!</p>
        <Button onClick={() => (window.location.href = '/ingest')}>
          Add New Note
        </Button>
      </div>
    );
  }

  const currentCard = cards[currentIndex];
  const progress = ((currentIndex + 1) / cards.length) * 100;

  return (
    <div className="container mx-auto px-4 py-8 max-w-2xl">
      {/* Progress */}
      <div className="mb-6">
        <div className="flex justify-between text-sm mb-2">
          <span>Card {currentIndex + 1} of {cards.length}</span>
          <span>Score: {stats.correct}/{stats.total}</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className="bg-blue-600 h-2 rounded-full transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Flashcard */}
      <Card className="p-8 min-h-[300px] flex flex-col justify-between">
        <div>
          <p className="text-sm text-gray-500 mb-4">Question</p>
          <p className="text-xl mb-6 whitespace-pre-wrap">{currentCard.question}</p>

          {showAnswer && (
            <div className="mt-6 p-4 bg-blue-50 rounded-lg">
              <p className="text-sm text-gray-500 mb-2">Answer</p>
              <p className="text-lg font-medium">{currentCard.answer}</p>
            </div>
          )}
        </div>

        {!showAnswer ? (
          <Button onClick={() => setShowAnswer(true)} className="w-full">
            Show Answer
          </Button>
        ) : (
          <div className="space-y-2">
            <p className="text-sm text-center text-gray-600 mb-2">How well did you know this?</p>
            <div className="grid grid-cols-3 gap-2">
              <Button
                variant="destructive"
                onClick={() => handleResponse(1)}
              >
                <XCircle className="mr-2 h-4 w-4" />
                Wrong
              </Button>
              <Button
                variant="outline"
                onClick={() => handleResponse(3)}
              >
                Hard
              </Button>
              <Button
                variant="default"
                onClick={() => handleResponse(5)}
              >
                <CheckCircle className="mr-2 h-4 w-4" />
                Easy
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Stats */}
      <div className="mt-4 text-center text-sm text-gray-600">
        <p>Times reviewed: {currentCard.times_reviewed}</p>
        <p>Accuracy: {currentCard.times_reviewed > 0 ? Math.round((currentCard.times_correct / currentCard.times_reviewed) * 100) : 0}%</p>
      </div>
    </div>
  );
}
```

---

### **Hour 19-20: Graph Visualization**

```typescript
// frontend/app/graph/page.tsx
'use client';

import { useEffect, useState } from 'react';
import { graphApi } from '@/lib/api';
import dynamic from 'next/dynamic';

// Dynamically import to avoid SSR issues
const ForceGraph = dynamic(() => import('@/components/ForceGraph'), { ssr: false });

export default function GraphPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadGraph();
  }, []);

  const loadGraph = async () => {
    try {
      const graphData = await graphApi.get();
      setData(graphData);
      setLoading(false);
    } catch (error) {
      console.error('Failed to load graph:', error);
      setLoading(false);
    }
  };

  if (loading) return <div className="p-8 text-center">Loading graph...</div>;

  if (!data || data.nodes.length === 0) {
    return (
      <div className="p-8 text-center">
        <p className="text-gray-600 mb-4">No concepts yet. Add some notes!</p>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col">
      <div className="p-4 border-b">
        <h1 className="text-2xl font-bold">Knowledge Graph</h1>
        <p className="text-sm text-gray-600">{data.nodes.length} concepts</p>
      </div>
      <div className="flex-1">
        <ForceGraph nodes={data.nodes} edges={data.edges} />
      </div>
    </div>
  );
}
```

```typescript
// frontend/components/ForceGraph.tsx
'use client';

import { useEffect, useRef } from 'react';

interface Node {
  id: string;
  label: string;
  description: string;
}

interface Edge {
  source: string;
  target: string;
  type: string;
}

interface ForceGraphProps {
  nodes: Node[];
  edges: Edge[];
}

export default function ForceGraph({ nodes, edges }: ForceGraphProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d')!;
    
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;

    // Simple force-directed layout (basic version)
    const nodeMap = new Map();
    const positions: any[] = [];

    // Initialize random positions
    nodes.forEach((node, i) => {
      const pos = {
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: 0,
        vy: 0,
      };
      positions.push(pos);
      nodeMap.set(node.id, i);
    });

    // Simple physics simulation
    const simulate = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Draw edges
      ctx.strokeStyle = '#ccc';
      ctx.lineWidth = 1;
      edges.forEach(edge => {
        const sourceIdx = nodeMap.get(edge.source);
        const targetIdx = nodeMap.get(edge.target);
        if (sourceIdx !== undefined && targetIdx !== undefined) {
          const source = positions[sourceIdx];
          const target = positions[targetIdx];
          ctx.beginPath();
          ctx.moveTo(source.x, source.y);
          ctx.lineTo(target.x, target.y);
          ctx.stroke();
        }
      });

      // Draw nodes
      nodes.forEach((node, i) => {
        const pos = positions[i];
        
        // Node circle
        ctx.fillStyle = '#3b82f6';
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, 8, 0, 2 * Math.PI);
        ctx.fill();

        // Label
        ctx.fillStyle = '#000';
        ctx.font = '12px sans-serif';
        ctx.fillText(node.label, pos.x + 12, pos.y + 4);
      });

      // Apply forces (simplified)
      positions.forEach((pos, i) => {
        // Repulsion from other nodes
        positions.forEach((other, j) => {
          if (i !== j) {
            const dx = pos.x - other.x;
            const dy = pos.y - other.y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const force = 100 / (dist * dist);
            pos.vx += (dx / dist) * force;
            pos.vy += (dy / dist) * force;
          }
        });

        // Attraction from edges
        edges.forEach(edge => {
          if (nodeMap.get(edge.source) === i) {
            const targetIdx = nodeMap.get(edge.target);
            if (targetIdx !== undefined) {
              const target = positions[targetIdx];
              const dx = target.x - pos.x;
              const dy = target.y - pos.y;
              pos.vx += dx * 0.01;
              pos.vy += dy * 0.01;
            }
          }
        });

        // Center attraction
        const cx = canvas.width / 2;
        const cy = canvas.height / 2;
        pos.vx += (cx - pos.x) * 0.001;
        pos.vy += (cy - pos.y) * 0.001;

        // Apply velocity with damping
        pos.vx *= 0.9;
        pos.vy *= 0.9;
        pos.x += pos.vx;
        pos.y += pos.vy;

        // Bounds
        pos.x = Math.max(20, Math.min(canvas.width - 20, pos.x));
        pos.y = Math.max(20, Math.min(canvas.height - 20, pos.y));
      });

      requestAnimationFrame(simulate);
    };

    simulate();
  }, [nodes, edges]);

  return <canvas ref={canvasRef} className="w-full h-full" />;
}
```

---

### **Hour 21-22: Navigation & Polish**

```typescript
// frontend/app/layout.tsx
import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import Link from 'next/link';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'GraphRecall MVP',
  description: 'Lifelong learning through active recall',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <nav className="border-b bg-white">
          <div className="container mx-auto px-4 py-4">
            <div className="flex items-center justify-between">
              <Link href="/" className="text-xl font-bold">
                GraphRecall
              </Link>
              <div className="flex gap-4">
                <Link href="/ingest" className="hover:text-blue-600">
                  Add Note
                </Link>
                <Link href="/review" className="hover:text-blue-600">
                  Review
                </Link>
                <Link href="/graph" className="hover:text-blue-600">
                  Graph
                </Link>
              </div>
            </div>
          </div>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
```

```typescript
// frontend/app/page.tsx
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { BookOpen, Brain, Network } from 'lucide-react';

export default function Home() {
  return (
    <div className="container mx-auto px-4 py-16">
      <div className="text-center mb-12">
        <h1 className="text-4xl font-bold mb-4">GraphRecall MVP</h1>
        <p className="text-xl text-gray-600">
          Your lifelong learning companion powered by AI
        </p>
      </div>

      <div className="grid md:grid-cols-3 gap-6 max-w-4xl mx-auto">
        <Card className="p-6 text-center hover:shadow-lg transition">
          <BookOpen className="h-12 w-12 mx-auto mb-4 text-blue-600" />
          <h2 className="text-xl font-semibold mb-2">Add Notes</h2>
          <p className="text-gray-600 mb-4">
            Upload markdown notes and extract concepts automatically
          </p>
          <Link href="/ingest">
            <Button className="w-full">Get Started</Button>
          </Link>
        </Card>

        <Card className="p-6 text-center hover:shadow-lg transition">
          <Brain className="h-12 w-12 mx-auto mb-4 text-green-600" />
          <h2 className="text-xl font-semibold mb-2">Daily Review</h2>
          <p className="text-gray-600 mb-4">
            Spaced repetition flashcards to ensure retention
          </p>
          <Link href="/review">
            <Button className="w-full">Start Review</Button>
          </Link>
        </Card>

        <Card className="p-6 text-center hover:shadow-lg transition">
          <Network className="h-12 w-12 mx-auto mb-4 text-purple-600" />
          <h2 className="text-xl font-semibold mb-2">Knowledge Graph</h2>
          <p className="text-gray-600 mb-4">
            Visualize your interconnected knowledge
          </p>
          <Link href="/graph">
            <Button className="w-full">Explore</Button>
          </Link>
        </Card>
      </div>
    </div>
  );
}
```

---

### **Hour 23: Testing & Bug Fixes**

```bash
# Test full flow
# 1. Start backend
cd backend
source venv/bin/activate
python -m app.main

# 2. Start frontend
cd frontend
npm run dev

# 3. Open browser: http://localhost:3000

# 4. Test workflow:
# - Go to "Add Note"
# - Paste sample note about "Neural Networks"
# - Submit
# - Check concepts extracted
# - Go to "Review"
# - Answer flashcards
# - Check "Graph" to see visualization
```

---

### **Hour 24: Documentation & Deployment**

```markdown
# GraphRecall MVP - README.md

## Setup

### Prerequisites
- Python 3.11+
- Node.js 20+
- Docker

### Installation

1. Clone repository
2. Start databases:
   ```bash
   docker-compose up -d
   ```

3. Backend:
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env  # Add your OPENAI_API_KEY
   python -m app.main
   ```

4. Frontend:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

5. Open http://localhost:3000

## Usage

1. **Add Notes**: Paste markdown content, system extracts concepts
2. **Review**: Daily flashcards with spaced repetition
3. **Graph**: Visualize knowledge connections

## Features

✅ Markdown ingestion
✅ Concept extraction (GPT-4o-mini)
✅ Knowledge graph (Neo4j)
✅ Auto-generated flashcards
✅ Spaced repetition (SM-2)
✅ Proficiency tracking
✅ Graph visualization

## Limitations (MVP)

- Single user only
- Markdown only (no PDFs, OCR, etc.)
- Basic synthesis (no conflict resolution)
- Local deployment
```

---

## **TESTING & DEPLOYMENT**

### **Test Cases**

```python
# backend/tests/test_ingestion.py
import pytest
from app.graphs.ingestion import ingestion_graph

@pytest.mark.asyncio
async def test_basic_ingestion():
    state = {
        "user_id": "test",
        "raw_content": "# Gradient Descent\n\nAn optimization algorithm.",
        "extracted_concepts": [],
        "created_concept_ids": []
    }
    
    result = await ingestion_graph.ainvoke(state)
    
    assert result["final_note_id"] is not None
    assert len(result["extracted_concepts"]) > 0
    assert len(result["created_concept_ids"]) > 0
```

---

## **POST-MVP ROADMAP**

### **Week 2: Enhanced Features**
- PDF support
- Better synthesis with conflict detection
- User authentication
- Multi-user support

### **Week 3: Multi-Modal**
- OCR for handwritten notes
- YouTube transcript processing
- Chat history integration

### **Week 4: Advanced**
- GitHub project analysis
- Dynamic resume
- Web scraping agent
- Teaching mode

---

## **FINAL CHECKLIST**

### **Day 1 Complete:**
- ✅ Databases running (PostgreSQL + Neo4j)
- ✅ Ingestion agent working
- ✅ Concepts extracted and stored
- ✅ Flashcards generated
- ✅ API endpoints functional

### **Day 2 Complete:**
- ✅ Frontend pages built
- ✅ Note ingestion UI
- ✅ Review interface
- ✅ Graph visualization
- ✅ Full workflow tested

### **Ready to Launch:**
- ✅ Documentation written
- ✅ README with setup instructions
- ✅ Basic tests passing
- ✅ Everything runs locally

---

## **SUCCESS!**

You now have a working GraphRecall MVP! 🎉

**Core Loop Working:**
Upload Note → Extract Concepts → Build Graph → Generate Flashcards → Daily Review → Track Proficiency

**What's Next:**
1. Use it yourself for a week
2. Identify pain points
3. Prioritize features from roadmap
4. Iterate!

**Remember:** This is an MVP. It's meant to validate the core idea. Don't worry about perfection - worry about whether the core learning loop works for you!
