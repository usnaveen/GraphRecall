# GraphRecall — Technical Report

*Naveen U S · November 2026 · Website: https://graphrecall.online · Code: https://github.com/usnaveen/GraphRecall*

## 1. The problem

People now learn from many places at once: papers, books, newsletters, YouTube, LeetCode and long chats with AI assistants. Two things go wrong. Most of it is forgotten within weeks, because nothing brings it back. And what you *do* know is invisible: to you (you can't list everything you know about machine learning) and to the AI tools you use, which explain everything from zero.

Knowledge graphs are fashionable, but most are pictures you look at once. GraphRecall builds an **active** graph of every concept you have been exposed to, and puts it to work in three ways:

1. A **daily feed** that brings concepts back at the right time (spaced repetition).
2. An **assistant** that answers from your own notes and knows your strengths and gaps.
3. An **MCP server**, so any agent can read what you know and explain at your level.

## 2. System overview

| Layer | Technology |
|---|---|
| iOS app | SwiftUI on iOS 26 (Liquid Glass), WKWebView + Three.js for the 3D graph, PDFKit, on-device dictation and OCR |
| API | FastAPI, LangGraph for ingestion and chat workflows |
| Storage | PostgreSQL + pgvector (notes, chunks, embeddings, reviews, evidence), Neo4j (concepts and typed relationships) |
| Models | Gemini Flash-Lite for extraction, chat and cards; Gemini embeddings; a Gemini image model ("Nano Banana") for illustrations; a local scikit-learn-trained classifier for intent routing |
| Agents | MCP over streamable HTTP, with scoped API keys and OAuth 2.1 |

## 3. Ingestion: from anything to concepts

**Inputs.** The Create tab accepts:
- typed concepts and text;
- web URLs and YouTube videos;
- exported chat histories;
- files and PDFs, including whole books;
- photos and scanned pages (on-device OCR);
- voice (on-device dictation).

The iOS share extension sends links and text from any app.

**Chunking.** Books go through a rule-based, image-aware chunker (`backend/services/book_chunker.py`) that makes no LLM calls:
- it keeps headings as hierarchy hints;
- it never separates a figure from its caption;
- it uses about 15% overlap between chunks.

Chunks are stored with their parent section. Retrieval matches small child windows and answers with the surrounding parent context.

**Concept extraction and merging.** An LLM extracts concepts with definitions, prerequisites and subtopics as structured output. Each concept is matched against your existing graph by normalised name and embedding similarity. It either **merges into an existing node**, adding new evidence and links, or **becomes a new node**. Relationships are typed and directed:
- `PREREQUISITE_OF`: A is needed for B;
- `SUBTOPIC_OF`: A is part of B;
- `BUILDS_ON`.

New nodes get link suggestions from vector neighbours plus same-domain hub concepts.

**Communities and subjects.** Louvain community detection groups concepts, and an LLM names each community and writes a short summary. A taxonomy map rolls communities up into subjects such as Machine Learning, Mathematics and Computer Science. On the author's graph that gives 507 concepts, about 2,184 links, 23 communities and 18 subjects. The app's graph opens on named communities; tapping one isolates it, and tapping a concept shows only its nearest prerequisites, subtopics and what it unlocks. A top "subjects" level, using the same hierarchy API, is being added.

**Figures.** Figures are cropped from your own PDFs. One is attached to a card only when its caption is genuinely about the concept: the name must take up a meaningful share of the caption's first sentence (`backend/services/concept_figures.py`). For concepts without a good figure, a Gemini image model draws an illustration in the app's style. When your sources contain a real figure of the concept, for example the Transformer diagram from *Attention Is All You Need*, that figure is sent as a reference and redrawn faithfully. The generated image is labelled as such on the card.

## 4. Retrieval: a hybrid GraphRAG pipeline

The assistant is a LangGraph workflow (`backend/graphs/chat_graph.py`) with five stages.

**4.1 Intent routing without an LLM call.** A small classifier decides what kind of question this is (explain, quiz, compare, summarize, …):
- word 1–2-gram TF-IDF and character 2–5-gram TF-IDF, concatenated, feeding a multinomial logistic regression;
- trained offline with scikit-learn, exported to JSON and re-implemented in plain numpy. Training asserts parity with sklearn (probability difference < 1e-6), so the API needs neither sklearn nor torch;
- when the classifier is confident it routes alone; otherwise one LLM call decides;
- every decision goes to `intent_decisions`, and a shadow mode records classifier and LLM side by side to measure agreement.

**4.2 Query analysis.** Follow-up questions ("and its time complexity?") are anchored to the previous turn's topic before retrieval. Concept names you already have in your graph are recognised in the message and become graph seeds.

**4.3 Local graph context.** The seed concepts plus vector-similar concepts pull in their neighbourhood from Neo4j: definitions, typed relationships and your mastery of each.

**4.4 Global search (GraphRAG), only when it helps.** For "summarize what I know about…" questions, community summaries are pre-selected by lexical overlap. A bounded map-reduce over them follows, with a cheap model scoring each community, and the results are combined. Other intents never fan out, which keeps latency and cost down.

**4.5 Hybrid chunk retrieval.** Three ranked lists are fused with Reciprocal Rank Fusion (k = 60):
1. pgvector similarity on chunk embeddings;
2. PostgreSQL full-text search;
3. a graph boost for chunks linked to the seed concepts.

Results are deduplicated by parent chunk, re-ranked by lexical overlap, then trimmed with MMR so the context isn't five copies of the same paragraph. The best chunks go first and last ("lost in the middle" ordering). The answer cites numbered sources. If your notes don't cover the question, it says so instead of pretending.

**4.6 Graph-chosen follow-ups at zero tokens.** Chat apps usually spend a second model call on "suggested questions". GraphRecall picks them from the graph around the concepts that grounded the answer:
- a **prerequisite you're shaky on**;
- a **subtopic you haven't studied**;
- **what the concept unlocks**.

It takes about 0.2 s and makes no LLM call (`backend/services/followups.py`). Taps are logged per suggestion type for click-through evaluation.

## 5. Caching

| Cache | What it saves | Correctness rule |
|---|---|---|
| Embedding cache (in-process L1, optional Redis L2) | Re-embedding the same query in the analysis, retrieval and answer stages | Keyed by model and vector width, because vectors from different models aren't comparable |
| Corpus-versioned response cache | A full RAG answer to a repeated question | Partitioned by user, a fingerprint of the user's notes and an explicit version counter. Any added or deleted note moves the partition, so a deleted note's text is never served from cache |
| Web search cache | Repeated research lookups | Keyed by the query |
| Knowledge-profile prefix (MCP) | Agents re-reading your profile | The profile is returned with a stable hash (`profile_prefix_hash`), so an agent can keep it as a cached prompt prefix and only fetch the per-question delta |

Not yet used: Gemini's explicit context caching for very long single-document Q&A. It's planned.

## 6. The learning loop

**Scheduling.** Reviews use FSRS (stability and difficulty per concept). When recall slips on a concept, scheduling **backtracks along prerequisite edges** and brings back the shaky foundations first.

**The feed.** A one-stop daily view, designed to feel like scrolling social media rather than homework: no goal rings or streak guilt, which matters for ADHD-prone learners.
- **Card types:** concept showcases, cloze term cards, multiple-choice quizzes, "spot the bug" cards and runnable code sandboxes (executed offline in a locked-down WKWebView). Articles and YouTube videos from sources you follow are each matched to concepts in your graph.
- **Daily limit:** a cap on concepts per day keeps it short.
- **Rating:** you rate how well you knew each card on Apple's native slider (No idea · Shaky · Got it · Easy), and that rating feeds FSRS.
- **Remind me:** any card can come back later.

**Evidence and the resume audit.** Each concept's status (strong / shaky / seen / unexposed) is computed from evidence: reviews, quiz answers, code results, self-ratings and notes. A resume is parsed and every claimed skill is checked against that evidence, so you see which claims you could defend and which need work. LeetCode problems are logged by number: title, difficulty, topics and a suggested pattern come from LeetCode's public API, and attempts schedule reviews.

## 7. Your knowledge as context for any agent (MCP)

GraphRecall runs an MCP server (streamable HTTP, `backend/agent_bridge/`). Claude, Cursor or any MCP client connects with a scoped key (`read:knowledge`, optionally `write:feed`). OAuth 2.1 with PKCE and dynamic client registration is implemented for hosted connectors. Host and Origin checks, per-key rate limits and an audit log protect it.

**Tools (15)** include:
- `get_knowledge_profile`, `search_concepts`, `get_concept_neighborhood`, `assess_concepts`, `list_due_reviews`;
- `get_knowledge_frontier`, which returns, for a task, what an agent needs to teach well:
  - **anchors:** concepts you know well, to explain through;
  - **frontier:** shaky prerequisites to refresh in a line;
  - **gaps:** prerequisites you've never seen;
  - **misconceptions:** from your wrong answers;
  - **provenance:** when and from which source you learned each;
  - **resume claims at risk**;
- `record_exposure`: the agent writes back what you learned in its session, so the graph grows from your conversations too;
- `propose_feed_items` and `suggest_for_later`: the agent can queue reading for your feed, and you approve it.

**Example.** Paste a research paper into Claude and ask it to explain:
1. Claude calls `get_knowledge_frontier` with the paper's key concepts.
2. It sees that you know attention well, are shaky on KV caching and have never seen speculative decoding.
3. It anchors on attention, refreshes KV caching in two lines and teaches speculative decoding properly.
4. With write access, it records that you've now been exposed to speculative decoding.

This works today from Claude Code against a local server. Public connectors (claude.ai, ChatGPT) are waiting on hosting.

## 8. Engineering notes

- **Tests:** unit and integration tests cover chat (27), follow-ups (7), LeetCode lookup (6) and the v3 backend (graph hierarchy, dictation stream, knowledge frontier, email ingest, overnight jobs: 71). An evaluation harness for retrieval and answer quality exists (`eval/graphrag/`); scores will be published now that paid API quota is available.
- **Cost discipline:** small models by default, zero-token routing and follow-ups where a model isn't needed, caches with correctness rules, and per-day usage tracking (`usage_daily`).
- **Privacy:** contact details are stripped from resumes server-side, and illustrations are labelled as generated. MCP keys are hashed at rest, revocable, and default to read-only.

## 9. What's next

- **Voice-to-graph in the app:** hold "+" and dictate concepts; they appear with links as you speak. The streaming endpoint exists.
- **A recall-outline screen:** "close your eyes and list machine learning".
- **Server-side storage** for resume PDFs.
- **Public hosting** on graphrecall.online (Hetzner or a Cloudflare Tunnel), so claude.ai and ChatGPT can connect over OAuth.
- **Ingestion:** newsletter email routing, plus nightly batch jobs on the cheapest model.
- **Published retrieval and answer-quality evaluation scores.**
