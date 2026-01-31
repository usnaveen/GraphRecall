# GraphRecall: Complete Project Context & Requirements
## **Compiled from All Conversations & Handwritten Notes**

---

## **1. PROJECT VISION (From Initial Conversation)**

### **Core Concept**
GraphRecall is a **lifelong active recall learning system** that grows with you. It's not just another note-taking app - it's a **living knowledge graph** that:

- Evolves as you learn more about topics
- Uses **active recall** and **spaced repetition** to ensure retention
- Synthesizes new information with existing knowledge (not just storage)
- Tests you on what you've learned through flashcards and quizzes
- Knows which concepts to ask you about every day

### **Key Philosophy**
- **Living Notes**: Notes aren't static - they evolve as you learn more
- **Anti-AI-Slop**: No generic AI-generated content - everything is synthesized from YOUR sources with proper attribution
- **Graph-Based Learning**: Concepts are interconnected, not isolated
- **Adaptive Testing**: The system knows what you're weak at and focuses on that

---

## **2. REQUIREMENTS FROM HANDWRITTEN NOTES**

### **From Image 1:**

**A Graph of Knowledge**
- Flashcards must be made on **important topics**
- Use **MCQ-type quizzes**
- Repeated quizzes on **mistaken concepts**
- YouTube video dumps → extract important points → store it on notes of relevant topic with source

**Data Flow:**
```
Data → Analyze → {
    ├─→ Append to existing notes (linked)
    └─→ Short notes on the source
}
```

**Mind Maps & Graphs**
- Create mind maps and graphs on a particular topic group
- Use **strong open-source OCR model** to get notes from handwritten images
- Build an engine that can take **handwritten text** and seamlessly convert it into some like handwritten notes on an iPad
- Must be able to move around text well and there on a notebook page (like it must detect like - this is a line, this is a sentence, and we must be able to move them around, change colors, and all that)
- **The novelty is digital minimalism of using real paper to concentrate and generate ideas without distraction** and be able to carry those knowledge everywhere

### **From Image 2:**

**Query System**
- When we query the app on some written notes that we have taken, it must bring to the screen the exact piece of text that we have written
- Even flashcards can be made with that exact bit of written text like important keywords can be closed, hidden, and asked to guess

**Chat History Integration**
- Input types can even be chat history of some AI agent
- In this case, our agent must be capable of understanding the conversation, where the user struggled to understand, or what was the final understanding, and take aways from the conversation
- **Part of the application must be a dynamic resume** that gets updated based on each of the skills we have acquired
- The must be a view, **not just the skills we have mentioned in our resume** from green to red based on our performances on each of that skill

**Web Scraping & Sanity Checks**
- The agent must scrape web periodically and update
- When we write notes on technical tools like say LangChain - and a new version is released and now the notes have to change, for this we must have an option to **run sanity checks using LangChain MCP** to understand the recent changes and then make appropriate changes on our notes and it has to update us on what are the changes

### **From Image 3:**

**Project Section on Resume**
- On the resume on the project section when we click on the respective project there should be quizzes and interview-based questions on the project based on the project GitHub repo and implementation details
- There should be a mode where we explain our concepts and we must get feedback on how correct we are

---

## **3. CORE FEATURES BREAKDOWN**

### **3.1 Input Types (Multi-Modal Ingestion)**
1. **Markdown files** - Basic text notes
2. **PDFs** - Books, papers, articles
3. **Handwritten notes** - OCR processing
4. **YouTube videos** - Transcript extraction + key point identification
5. **Chat history** - Conversation with AI agents
6. **GitHub repositories** - Code analysis for project-based learning
7. **Web content** - Scraped documentation

### **3.2 Knowledge Graph**
- **Concepts as Nodes**: Each concept is a node with relationships
- **Relationships**: PREREQUISITE_OF, RELATES_TO, CONTRADICTS, BUILDS_ON
- **Source Attribution**: Every concept links back to source material
- **Version History**: Track how understanding evolved over time

### **3.3 Synthesis Engine (Anti-Slop Core)**
When new information arrives:
1. **Find existing related knowledge** (vector search + graph traversal)
2. **Compare quality**: Is new info better/different/complementary?
3. **Synthesis strategies**:
   - **Merge**: Combine if complementary
   - **Add Perspective**: Keep both if different angles
   - **Flag Conflict**: Human review if contradictory
4. **Validate**: No hallucinations - check all content is from sources
5. **Attribute**: Every piece knows its source

### **3.4 Active Recall System**

**Flashcard Types:**
- **Cloze deletion**: Fill-in-the-blank with hidden keywords
- **MCQs**: Multiple choice generated from concept relationships
- **Explanation cards**: "Explain X in your own words"
- **Relationship cards**: "How does A relate to B?"

**Spaced Repetition:**
- SM-2 or Anki-like algorithm
- Adaptive based on:
  - Your performance
  - Concept importance
  - Recency of use
  - Graph interconnection density

**Daily Quiz Selection:**
- Due for review (spaced repetition)
- Recently added (reinforcement)
- User-selected topics
- Weakest areas (lowest confidence scores)
- Related to current projects/goals

### **3.5 Interactive Features**

**Mind Map Visualization:**
- Force-directed graph of concepts
- Color by proficiency (red: weak, green: strong)
- Size by importance (centrality)
- Click to explore, start quiz, or see notes

**Handwritten Notes Interface:**
- Movable text blocks
- Draw connections
- Color coding
- Export as image/PDF
- Like digital paper experience

**Teaching Mode:**
- Explain concepts to the app
- Get feedback on accuracy
- Socratic questioning

### **3.6 Dynamic Resume**
- **Skills section**: Auto-updated from knowledge graph
- **Proficiency colors**: Green (fresh) → Yellow (needs review) → Red (stale)
- **Project section**: Click project → get quizzes on implementation
- **Interview mode**: Practice explaining your projects

### **3.7 Web Scraping & Updates**
- Monitor URLs for changes (docs, blogs, tools)
- Detect when library versions change
- Flag outdated notes
- Suggest updates
- **LangChain MCP integration**: Sanity check against latest docs

---

## **4. TECHNICAL ARCHITECTURE**

### **4.1 Stack**
- **Backend**: Python + FastAPI + LangGraph 1.0+
- **Databases**: 
  - Neo4j (knowledge graph)
  - PostgreSQL (content, proficiency, flashcards)
  - SqliteSaver (LangGraph checkpoints)
- **AI Models**:
  - OpenAI GPT-4o-mini (extraction, cheap tasks)
  - OpenAI GPT-4o (flashcard generation, quality)
  - Anthropic Claude Sonnet 4.5 (synthesis, teaching mode)
- **Frontend**: Next.js + React + Tailwind + shadcn/ui
- **Visualization**: React Flow (graphs), D3.js (mind maps)

### **4.2 LangGraph Agents**

**1. Ingestion Agent**
- Parse input (markdown, PDF, handwriting, video, chat)
- Extract concepts
- Find related existing knowledge
- Route to synthesis if needed

**2. Synthesis Agent**
- Compare new vs existing content
- Detect overlaps and conflicts
- Choose strategy (merge/perspective/conflict)
- Validate no hallucinations
- Update graph with attributions

**3. Flashcard Generation Agent**
- Generate cloze cards
- Generate MCQs
- Generate explanation questions
- Quality filter
- User approval checkpoint

**4. Review Agent**
- Fetch due cards (spaced repetition)
- Identify weak areas
- Mix cards optimally
- Present cards
- Update proficiency scores

**5. Web Scraping Agent**
- Monitor tracked URLs
- Detect significant changes
- Find affected notes
- Create update tasks
- Send notifications

**6. Project Analysis Agent**
- Clone GitHub repo
- Analyze code structure
- Identify tech stack
- Generate implementation questions
- Create project-specific quizzes

### **4.3 Key Workflows**

**Note Ingestion Flow:**
```
Upload Note → Extract Concepts → Find Related → 
  ├─→ No Overlap → Store New
  └─→ Overlap Detected → Synthesis Agent → User Approval → Merge
```

**Daily Review Flow:**
```
Start Session → Generate Queue (Due + Weak + Topics) → 
  Loop: Present Card → User Responds → Update SRS → Next Card
  → Session Complete → Update Proficiency
```

**Conflict Resolution:**
```
New Info → Contradiction Detected → Create Review Task → 
  User Reviews → Choose Resolution → Update Graph
```

---

## **5. DATA MODELS**

### **5.1 PostgreSQL Tables**

```sql
-- Core tables
users (id, email, password, settings)
notes (id, user_id, content, format, graph_node_id, embedding)
proficiency_scores (user_id, concept_id, score, next_review_due)
flashcards (id, concept_id, question, answer, ease_factor, next_review)
study_sessions (id, user_id, type, concepts_covered, performance)
conflict_queue (id, concept_id, existing_note, new_content, status)
```

### **5.2 Neo4j Graph**

```cypher
// Nodes
(:Concept {id, name, description, complexity_score})
(:Topic {id, name})
(:NoteSource {id, note_id, summary})

// Relationships
(:Concept)-[:PREREQUISITE_OF]->(:Concept)
(:Concept)-[:RELATED_TO {strength}]->(:Concept)
(:Concept)-[:CONTRADICTS]->(:Concept)
(:NoteSource)-[:EXPLAINS {relevance}]->(:Concept)
(:Concept)-[:EVOLVED_FROM {timestamp}]->(:Concept)
```

---

## **6. USER EXPERIENCE FLOW**

### **Daily Usage**
1. **Morning**: Check "Today's Review Queue" (5-20 flashcards)
2. **Learning**: Upload new notes/videos → See synthesis happen
3. **Studying**: Explore mind map → Click concept → Take quiz
4. **Evening**: Review performance → See proficiency improve

### **Note Taking Flow**
1. Upload markdown or handwritten note
2. System extracts concepts
3. Shows related existing notes
4. If overlap: proposes synthesis
5. User approves/modifies
6. Graph updates
7. Flashcards auto-generated
8. Added to review queue

### **Review Session**
1. Click "Start Daily Review"
2. Get mixed cards (due, weak, chosen topics)
3. Answer each card
4. Get immediate feedback
5. See proficiency update in real-time
6. End with stats (accuracy, streak, etc.)

---

## **7. UNIQUE FEATURES (Differentiators)**

### **What Makes GraphRecall Different:**

1. **Living Notes**: 
   - Not append-only like Obsidian
   - Active synthesis with conflict detection
   - Source attribution for every piece

2. **Graph-First Learning**:
   - Spaced repetition respects concept dependencies
   - If you fail Concept A, review its prerequisites
   - Visual exploration of knowledge structure

3. **Anti-Slop Mechanisms**:
   - Hallucination validation
   - Source-only synthesis
   - User approval gates
   - Quality scoring

4. **Multi-Modal Input**:
   - Handwriting → Digital (with spatial preservation)
   - YouTube → Timestamped notes
   - Chat history → Key learnings
   - GitHub → Project quizzes

5. **Dynamic Resume**:
   - Skills auto-tracked from learning
   - Proficiency decay visualization
   - Project-based interview prep

6. **Proactive Updates**:
   - Monitors docs for changes
   - Flags outdated notes
   - Suggests corrections
   - Keeps knowledge fresh

---

## **8. SUCCESS CRITERIA**

### **MVP Must Have:**
- ✅ Upload markdown notes
- ✅ Extract concepts automatically
- ✅ Build knowledge graph
- ✅ Generate flashcards
- ✅ Daily review with spaced repetition
- ✅ Basic synthesis (merge notes)
- ✅ Visualize graph
- ✅ Track proficiency

### **Phase 2 Features:**
- OCR for handwritten notes
- YouTube transcript processing
- Chat history analysis
- Mind map visualization
- Teaching mode

### **Phase 3 Features:**
- GitHub project analysis
- Web scraping agent
- Dynamic resume
- Interactive handwriting canvas
- Collaboration features

---

## **9. NON-FUNCTIONAL REQUIREMENTS**

### **Performance:**
- Note ingestion < 5 seconds (including LLM calls)
- Flashcard generation < 3 seconds
- Graph query < 500ms
- UI responsive < 100ms

### **Scalability:**
- Support 10,000+ concepts per user
- Handle 1000+ notes
- 100+ concurrent users

### **Data Integrity:**
- All synthesized content traceable to sources
- Version history for all knowledge
- Backup checkpoints for LangGraph workflows
- No data loss on failures

### **User Experience:**
- Minimal clicks to start review
- Progress visible in real-time
- Clear feedback on performance
- Beautiful, distraction-free interface

---

## **10. EDGE CASES & CONSIDERATIONS**

### **Synthesis Edge Cases:**
- What if new note completely contradicts old knowledge?
  → Flag for manual review, don't auto-merge
- What if overlap is 50%?
  → Add as "Alternative Perspective" section
- What if source quality is questionable?
  → Store separately, let user decide

### **Review Edge Cases:**
- User on vacation for 2 weeks, 500 cards due
  → Cap daily review at 50, distribute over time
- User perfect on all cards
  → Increase interval exponentially
- Concept has no flashcards yet
  → Trigger auto-generation

### **Graph Edge Cases:**
- Circular dependencies (A prerequisite of B, B prerequisite of A)
  → Detect cycles, flag for user
- Orphaned concepts (no connections)
  → Suggest potential relationships
- Redundant concepts (duplicates)
  → Merge nodes, preserve history

---

## **11. DEVELOPMENT PRIORITIES**

### **For 2-Day MVP:**

**Day 1 (Backend Core):**
1. Database setup (PostgreSQL + Neo4j + Docker)
2. Basic ingestion agent (markdown only)
3. Concept extraction (GPT-4o-mini)
4. Simple graph storage
5. Flashcard generation (basic cloze cards)
6. FastAPI endpoints

**Day 2 (Review System + UI):**
1. Spaced repetition logic
2. Review agent
3. Basic Next.js UI
4. Note upload page
5. Daily review interface
6. Simple graph visualization
7. Connect everything

**What to Skip in MVP:**
- Handwriting OCR
- YouTube processing
- Chat history
- GitHub analysis
- Web scraping
- Dynamic resume
- Teaching mode
- Advanced synthesis

**Focus on Core Loop:**
Upload Note → Extract Concepts → Build Graph → Generate Cards → Review Daily

---

## **12. TECH DEBT TO ACCEPT FOR MVP**

- Hardcoded user (no auth)
- In-memory only for some state
- Basic UI (no fancy animations)
- Single LLM provider (OpenAI only)
- Simple synthesis (auto-merge, no conflicts)
- Local deployment only
- No mobile app
- Limited error handling

**BUT MUST HAVE:**
- LangGraph for agent orchestration ✅
- Neo4j for graph ✅
- PostgreSQL for data ✅
- Proper state management ✅
- Working spaced repetition ✅
- Real flashcards that work ✅

---

## **SUMMARY**

GraphRecall is ambitious but achievable. The 2-day MVP focuses on the **core learning loop**: ingest → extract → graph → flashcards → review. Everything else (OCR, videos, dynamic resume, etc.) comes in later phases.

The key innovation is the **synthesis engine** - making notes evolve rather than accumulate. Even in MVP, we implement basic synthesis. The **spaced repetition + graph traversal** makes review smarter than traditional SRS.

**Next Step**: Build the detailed 2-day implementation guide with complete code snippets for every component.
