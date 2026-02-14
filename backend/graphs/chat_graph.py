"""
LangGraph Chat Workflow

Modern LangGraph implementation for GraphRAG chat with:
- MessagesState pattern with add_messages reducer
- ToolNode for graph and notes search
- Proper LangChain message types (System/Human/AI)
- Checkpoint persistence for conversation memory

Flow:
START → analyze_query → (conditional) → [tools] → get_context → generate_response → END
"""

import json
from typing import Annotated, Literal, Optional

import structlog
from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
    BaseMessage,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from backend.config.llm import get_chat_model, get_embeddings
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.graphs.checkpointer import get_checkpointer

logger = structlog.get_logger()


# ============================================================================
# State Definition (MessagesState Pattern)
# ============================================================================


class ChatState(TypedDict, total=False):
    """
    LangGraph state for chat with MessagesState pattern.
    
    Uses add_messages reducer for automatic message history management.
    This is the interview-ready pattern for conversation state.
    """
    # Core message history with add_messages reducer
    messages: Annotated[list[BaseMessage], add_messages]
    
    # User context
    user_id: str
    
    # Source-scoped filtering (optional)
    # When provided, retrieval is limited to these specific note/concept IDs
    focused_source_ids: list[str]
    
    # Query analysis
    intent: str
    entities: list[str]
    
    # Retrieved context
    graph_context: dict
    rag_context: list[dict]
    
    # Final outputs
    related_concepts: list[dict]
    sources: list[dict]



# ============================================================================
# Tool Definitions (@tool decorator pattern)
# ============================================================================


@tool
async def search_knowledge_graph(query: str, entities: list[str] = None) -> str:
    """
    Search the user's knowledge graph for concepts and relationships.
    
    Args:
        query: Natural language search query
        entities: Optional list of specific concept names to look up
    
    Returns:
        Formatted string with concepts and relationships found
    """
    logger.info("search_knowledge_graph: Searching", query=query, entities=entities)
    
    try:
        neo4j = await get_neo4j_client()
        
        if entities:
            # Direct lookup by entity names
            concepts = []
            for entity in entities[:5]:  # Limit to 5
                result = await neo4j.execute_query(
                    """
                    MATCH (c:Concept)
                    WHERE toLower(c.name) CONTAINS toLower($name)
                    RETURN c.id as id, c.name as name, c.definition as definition, 
                           c.domain as domain
                    LIMIT 3
                    """,
                    {"name": entity}
                )
                concepts.extend(result)
            
            if not concepts:
                return "No matching concepts found in your knowledge graph."
            
            # Get relationships between found concepts
            concept_ids = [c["id"] for c in concepts if c.get("id")]
            relationships = []
            
            if concept_ids:
                rel_result = await neo4j.execute_query(
                    """
                    MATCH (c1:Concept)-[r]->(c2:Concept)
                    WHERE c1.id IN $ids OR c2.id IN $ids
                    RETURN c1.name as from_name, type(r) as rel_type, c2.name as to_name
                    LIMIT 10
                    """,
                    {"ids": concept_ids}
                )
                relationships = rel_result
            
            # Format response
            output = "## Concepts Found:\n"
            for c in concepts:
                output += f"- **{c['name']}**: {c.get('definition', 'No definition')}\n"
            
            if relationships:
                output += "\n## Relationships:\n"
                for r in relationships:
                    output += f"- {r['from_name']} → {r['rel_type']} → {r['to_name']}\n"
            
            return output
        
        else:
            # Broad search using query keywords
            result = await neo4j.execute_query(
                """
                MATCH (c:Concept)
                WHERE toLower(c.name) CONTAINS toLower($query)
                   OR toLower(c.definition) CONTAINS toLower($query)
                RETURN c.id as id, c.name as name, c.definition as definition
                LIMIT 5
                """,
                {"query": query}
            )
            
            if not result:
                return f"No concepts found matching '{query}'."
            
            output = "## Matching Concepts:\n"
            for c in result:
                output += f"- **{c['name']}**: {c.get('definition', '')}\n"
            
            return output
            
    except Exception as e:
        logger.error("search_knowledge_graph: Failed", error=str(e))
        return f"Error searching knowledge graph: {str(e)}"


@tool
async def search_notes(query: str, user_id: str = "default") -> str:
    """
    Search the user's notes using semantic similarity.
    
    Args:
        query: Natural language search query
        user_id: User ID to filter notes
    
    Returns:
        Formatted string with relevant note excerpts
    """
    logger.info("search_notes: Searching", query=query, user_id=user_id)
    
    try:
        pg_client = await get_postgres_client()

        # Try vector similarity search on chunks first
        try:
            embeddings_model = get_embeddings()
            query_embedding = await embeddings_model.aembed_query(query)
            embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"

            result = await pg_client.execute_query(
                """
                SELECT c.id, n.title, c.content, c.page_start, c.page_end,
                       1 - (c.embedding <=> cast(:embedding as vector)) as similarity
                FROM chunks c
                JOIN notes n ON c.note_id = n.id
                WHERE n.user_id = :user_id
                  AND c.chunk_level = 'child'
                  AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> cast(:embedding as vector)
                LIMIT 5
                """,
                {"user_id": user_id, "embedding": embedding_literal}
            )
        except Exception:
            # Fallback to keyword search if vector search fails
            result = await pg_client.execute_query(
                """
                SELECT id, title, content_text as content, created_at
                FROM notes
                WHERE user_id = :user_id
                  AND (title ILIKE :search_pattern OR content_text ILIKE :search_pattern)
                ORDER BY created_at DESC
                LIMIT 5
                """,
                {"user_id": user_id, "search_pattern": f"%{query}%"}
            )

        if not result:
            return f"No notes found matching '{query}'."

        output = "## Relevant Notes:\n\n"
        for note in result:
            title = note.get("title", "Untitled")
            content = note.get("content", "")[:300]
            similarity = note.get("similarity")
            sim_tag = f" (relevance: {similarity:.2f})" if similarity else ""
            output += f"### {title}{sim_tag}\n{content}...\n\n"

        return output

    except Exception as e:
        logger.error("search_notes: Failed", error=str(e))
        return f"Error searching notes: {str(e)}"


# Define tools list for ToolNode
chat_tools = [search_knowledge_graph, search_notes]


# ============================================================================
# Node Functions
# ============================================================================


# ============================================================================
# Structured Output Models
# ============================================================================

from pydantic import Field

class QueryAnalysis(BaseModel):
    """Structured analysis of user query."""
    intent: Literal["explain", "compare", "find", "summarize", "quiz", "path", "general"] = Field(
        description="The primary intent of the user's query"
    )
    entities: list[str] = Field(
        default_factory=list,
        description="List of specific concept, topic, or technology names mentioned"
    )
    needs_search: bool = Field(
        default=False,
        description="True if the query requires searching the knowledge graph or notes"
    )


async def analyze_query_node(state: ChatState) -> dict:
    """
    Node 1: Analyze the user's query to determine intent and extract entities.
    
    Refactored to use function calling (with_structured_output) for 100% reliability.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "general", "entities": []}
    
    # Get the last human message
    last_message = messages[-1]
    query = last_message.content if hasattr(last_message, "content") else str(last_message)
    
    logger.info("analyze_query_node: Analyzing", query=query[:100])
    
    # LLM for query analysis with structured output (Gemini)
    # Using default model (gemini-2.5-flash) which supports function calling
    llm = get_chat_model(temperature=0)
    
    system_prompt = """Analyze the user's query to determine their intent and extract relevant entities.

    Intents:
    - explain: Asking for an explanation of a concept
    - compare: Asking to compare two or more things
    - find: Looking for specific facts or notes
    - summarize: Requesting a summary of a topic
    - quiz: Asking to be quizzed
    - path: Asking for a learning path or prerequisites
    - general: General conversation or greeting

    Entities:
    - Extract ONLY proper nouns, specific technologies, or defined concepts.
    - Do not extract generic words like "how", "why", "best".
    """
    
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Query: {query}")
    ])
    
    try:
        # Use LangChain's with_structured_output for robust extraction
        structured_llm = llm.with_structured_output(QueryAnalysis)
        response: QueryAnalysis = await structured_llm.ainvoke(prompt.format_messages())
        
        logger.info(
            "analyze_query_node: Complete",
            intent=response.intent,
            entities=response.entities,
        )
        
        return {
            "intent": response.intent,
            "entities": response.entities,
        }
        
    except Exception as e:
        logger.error("analyze_query_node: Failed", error=str(e))
        # Fallback to general intent on failure
        return {"intent": "general", "entities": []}


async def get_context_node(state: ChatState) -> dict:
    """
    Node 2: Retrieve context from knowledge graph and notes.
    
    Combines graph traversal with RAG retrieval.
    Supports source-scoped filtering when focused_source_ids is provided.
    """
    entities = state.get("entities", [])
    user_id = state.get("user_id", "default")
    messages = state.get("messages", [])
    focused_source_ids = state.get("focused_source_ids", [])  # Source-scoped filtering
    intent = state.get("intent", "general")
    
    last_message = messages[-1] if messages else None
    query = last_message.content if last_message and hasattr(last_message, "content") else ""
    
    logger.info(
        "get_context_node: Retrieving context",
        entities=entities,
        focused_sources=len(focused_source_ids) if focused_source_ids else 0,
    )
    
    graph_context = {"concepts": [], "relationships": []}
    rag_context = []
    
    # Get graph context
    if entities:
        try:
            neo4j = await get_neo4j_client()

            seed_concepts: list[dict] = []
            for entity in entities[:5]:
                # If source-scoped, filter concepts to only those in focused IDs
                if focused_source_ids:
                    result = await neo4j.execute_query(
                        """
                        MATCH (c:Concept)
                        WHERE c.id IN $source_ids
                          AND c.user_id = $user_id
                          AND (toLower(c.name) CONTAINS toLower($name) 
                               OR toLower(c.definition) CONTAINS toLower($name))
                          AND coalesce(c.confidence, 0.8) >= 0.4
                        RETURN c.id as id, c.name as name, c.definition as definition,
                               c.domain as domain, c.confidence as confidence
                        ORDER BY c.confidence DESC
                        LIMIT 3
                        """,
                        {"name": entity, "source_ids": focused_source_ids, "user_id": user_id}
                    )
                else:
                    result = await neo4j.execute_query(
                        """
                        MATCH (c:Concept)
                        WHERE c.user_id = $user_id
                          AND toLower(c.name) CONTAINS toLower($name)
                          AND coalesce(c.confidence, 0.8) >= 0.4
                        RETURN c.id as id, c.name as name, c.definition as definition,
                               c.domain as domain, c.confidence as confidence
                        ORDER BY c.confidence DESC
                        LIMIT 3
                        """,
                        {"name": entity, "user_id": user_id}
                    )
                seed_concepts.extend(result)

            concept_ids = list({c["id"] for c in seed_concepts if c.get("id")})
            if concept_ids:
                if intent == "path":
                    max_hops = 3
                    rel_types = ["PREREQUISITE_OF"]
                elif intent == "explain":
                    max_hops = 1
                    rel_types = None
                else:
                    max_hops = 2
                    rel_types = None

                hop_result = await neo4j.k_hop_context(
                    concept_ids=concept_ids,
                    user_id=user_id,
                    max_hops=max_hops,
                    max_nodes=20,
                    relationship_types=rel_types,
                    allowed_concept_ids=focused_source_ids or None,
                )
                graph_context["concepts"] = hop_result.get("nodes", seed_concepts)
                graph_context["relationships"] = hop_result.get("edges", [])
            else:
                graph_context["concepts"] = seed_concepts

        except Exception as e:
            logger.warning("get_context_node: Graph query failed", error=str(e))

    # Global Search: Map-Reduce over community summaries (Microsoft GraphRAG pattern)
    # Trigger when: intent is summarize/general, or no graph concepts found
    if intent in ("summarize", "general") or not graph_context.get("concepts"):
        try:
            from backend.services.community_service import CommunityService
            community_svc = CommunityService()

            # Use level-1 (medium) communities for global queries
            summaries = await community_svc.get_community_summaries_by_level(user_id, level=1)
            if not summaries:
                summaries = await community_svc.get_community_summaries_by_level(user_id)

            if summaries and len(summaries) >= 2:
                # MAP PHASE: Score each community's relevance to query
                map_llm = get_chat_model(temperature=0)
                map_results = []

                for s in summaries[:12]:
                    map_prompt = (
                        f"Given the user's question: \"{query}\"\n\n"
                        f"And this community of concepts:\n"
                        f"Title: {s['title']} ({s['size']} concepts)\n"
                        f"Summary: {s['summary']}\n\n"
                        f"Rate relevance 0-10 and provide a 1-2 sentence partial answer "
                        f"if relevant. Format: SCORE: X\nANSWER: ...\n"
                        f"If not relevant, respond: SCORE: 0\nANSWER: Not relevant."
                    )
                    try:
                        map_resp = await map_llm.ainvoke(map_prompt)
                        text = map_resp.content.strip()
                        score = 0
                        answer = text
                        for line in text.split("\n"):
                            if line.strip().upper().startswith("SCORE:"):
                                try:
                                    score = int(line.split(":", 1)[1].strip().split()[0])
                                except (ValueError, IndexError):
                                    score = 0
                            elif line.strip().upper().startswith("ANSWER:"):
                                answer = line.split(":", 1)[1].strip()

                        if score > 2:
                            map_results.append({
                                "title": s["title"],
                                "score": score,
                                "answer": answer,
                                "size": s["size"],
                            })
                    except Exception as e:
                        logger.warning("Global search map failed", community=s["title"], error=str(e))
                        continue

                # REDUCE PHASE: Combine top results into global context
                map_results.sort(key=lambda x: x["score"], reverse=True)
                top_results = map_results[:5]

                if top_results:
                    global_text = "\n".join(
                        f"- **{r['title']}** (relevance: {r['score']}/10, {r['size']} concepts): {r['answer']}"
                        for r in top_results
                    )
                    graph_context["global_summary"] = global_text
                    graph_context["search_mode"] = "global_map_reduce"
            elif summaries:
                global_text = "\n".join(
                    f"- **{s['title']}** ({s['size']} concepts): {s['summary']}" for s in summaries
                )
                graph_context["global_summary"] = global_text
                graph_context["search_mode"] = "global_simple"
        except Exception as e:
            logger.warning("get_context_node: Global search failed", error=str(e))

    # Get RAG context (notes) — Vector similarity search with parent chunk join
    if query:
        try:
            pg_client = await get_postgres_client()

            # Generate query embedding for vector similarity search
            embeddings_model = get_embeddings()
            query_embedding = await embeddings_model.aembed_query(query)
            embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"

            if focused_source_ids:
                result = await pg_client.execute_query(
                    """
                    SELECT c.id, c.content, c.images, c.chunk_index,
                           c.page_start, c.page_end,
                           p.content as parent_content,
                           n.title, n.id AS note_id,
                           1 - (c.embedding <=> cast(:embedding as vector)) as similarity
                    FROM chunks c
                    LEFT JOIN chunks p ON c.parent_chunk_id = p.id
                    JOIN notes n ON c.note_id = n.id
                    WHERE n.user_id = :user_id
                      AND n.id = ANY(:source_ids)
                      AND c.chunk_level = 'child'
                      AND c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> cast(:embedding as vector)
                    LIMIT 5
                    """,
                    {"user_id": user_id, "source_ids": focused_source_ids, "embedding": embedding_literal},
                )
            else:
                result = await pg_client.execute_query(
                    """
                    SELECT c.id, c.content, c.images, c.chunk_index,
                           c.page_start, c.page_end,
                           p.content as parent_content,
                           n.title, n.id AS note_id,
                           1 - (c.embedding <=> cast(:embedding as vector)) as similarity
                    FROM chunks c
                    LEFT JOIN chunks p ON c.parent_chunk_id = p.id
                    JOIN notes n ON c.note_id = n.id
                    WHERE n.user_id = :user_id
                      AND c.chunk_level = 'child'
                      AND c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> cast(:embedding as vector)
                    LIMIT 5
                    """,
                    {"user_id": user_id, "embedding": embedding_literal},
                )

            rag_context = []
            for row in result or []:
                row_dict = dict(row)
                images = row_dict.get("images")
                if isinstance(images, str):
                    try:
                        images = json.loads(images)
                    except Exception:
                        images = []
                row_dict["images"] = images or []
                # Use parent content for richer context if available
                parent_content = row_dict.get("parent_content")
                if parent_content:
                    row_dict["content"] = parent_content
                rag_context.append(row_dict)

        except Exception as e:
            logger.warning("get_context_node: Notes query failed", error=str(e))
    
    logger.info(
        "get_context_node: Complete",
        num_concepts=len(graph_context["concepts"]),
        num_notes=len(rag_context),
        scoped=bool(focused_source_ids),
    )
    
    return {
        "graph_context": graph_context,
        "rag_context": rag_context,
    }



async def generate_response_node(state: ChatState) -> dict:
    """
    Node 3: Generate response using retrieved context.
    
    Uses proper LangChain message types with MessagesPlaceholder.
    """
    messages = state.get("messages", [])
    intent = state.get("intent", "general")
    graph_context = state.get("graph_context", {})
    rag_context = state.get("rag_context", [])
    
    logger.info("generate_response_node: Generating", intent=intent)
    
    # Format context
    context_parts = []
    
    if graph_context.get("concepts"):
        concept_lines = []
        for c in graph_context["concepts"]:
            name = c.get("name", "Unknown")
            hops = c.get("hops", 0)
            conf = c.get("confidence", 0.8)
            if conf >= 0.85:
                conf_tag = " [high confidence]"
            elif conf < 0.5:
                conf_tag = " [low confidence]"
            else:
                conf_tag = ""
            if hops and hops >= 2:
                concept_lines.append(f"- {name}{conf_tag} (hop {hops})")
            else:
                suffix = f" (hop {hops})" if hops else ""
                concept_lines.append(
                    f"- {name}{conf_tag}{suffix}: {c.get('definition', 'No definition')}"
                )
        concepts_text = "\n".join(concept_lines)
        context_parts.append(f"**Knowledge Graph Concepts:**\n{concepts_text}")

    if graph_context.get("global_summary"):
        context_parts.append(
            f"**Global Summary:**\n{graph_context['global_summary']}"
        )

    if graph_context.get("relationships"):
        rel_lines = []
        for r in graph_context["relationships"][:15]:
            src = r.get('src_name') or r.get('src')
            tgt = r.get('tgt_name') or r.get('tgt')
            rel_type = r.get('type')
            strength = r.get('strength', 1.0)
            strength_tag = f" (strength: {strength:.1f})" if strength < 1.0 else ""
            rel_lines.append(f"- {src} --[{rel_type}]--> {tgt}{strength_tag}")
        rels_text = "\n".join(rel_lines)
        context_parts.append(f"**Relationships:**\n{rels_text}")
    
    if rag_context:
        note_lines = []
        for n in rag_context:
            page_start = n.get("page_start")
            page_end = n.get("page_end")
            page_text = ""
            if page_start:
                page_text = (
                    f" (p. {page_start}-{page_end})"
                    if page_end and page_end != page_start
                    else f" (p. {page_start})"
                )
            note_lines.append(
                f"- {n.get('title', 'Note')}{page_text}: {n.get('content', '')[:200]}..."
                + (f" [images: {len(n.get('images', []))}]" if n.get("images") else "")
            )
        notes_text = "\n".join(note_lines)
        context_parts.append(f"**Relevant Notes:**\n{notes_text}")
    
    context = "\n\n".join(context_parts) if context_parts else "No specific context found."
    
    # Intent-specific system prompts
    intent_instructions = {
        "explain": "Provide a clear, educational explanation.",
        "compare": "Compare and contrast the concepts.",
        "find": "Find and present the specific information.",
        "summarize": "Provide a concise summary.",
        "quiz": "Generate a quiz question about the topic.",
        "path": "Outline a learning path with prerequisites.",
        "general": "Provide a helpful response.",
    }
    
    instruction = intent_instructions.get(intent, intent_instructions["general"])
    
    # Build prompt with proper message types (Gemini)
    llm = get_chat_model(temperature=0.3)
    
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=f"""You are GraphRecall, a knowledge assistant helping users learn from their notes.

**Context from User's Knowledge Base:**
{context}

**Instructions:** {instruction}

**Citation Guidelines:**
1. When referencing specific information from the context, include a citation number in brackets like [1], [2]
2. Each citation should correspond to a source in the context
3. Use citations to show where facts come from
4. Be conversational but educational
5. If context is insufficient, suggest they add notes"""),
        MessagesPlaceholder(variable_name="history"),
    ])
    
    # Format messages (last 6 messages for context)
    history = messages[-6:] if len(messages) > 6 else messages
    
    try:
        formatted = prompt.format_messages(history=history)
        # Add tag for streaming filter in chat router
        response = await llm.with_config({"tags": ["final_response"]}).ainvoke(formatted)
        
        logger.info("generate_response_node: Complete")
        
        # Return with AI message added to state plus full metadata
        return {
            "messages": [AIMessage(content=response.content)],
            "related_concepts": [
                {"id": c.get("id"), "name": c.get("name")}
                for c in graph_context.get("concepts", [])
            ],
            "sources": [
                {
                    "id": n.get("id"),
                    "title": n.get("title"),
                    "content": n.get("content", "")[:500],
                    "images": n.get("images", []),
                    "note_id": n.get("note_id"),
                    "page_start": n.get("page_start"),
                    "page_end": n.get("page_end"),
                }
                for n in rag_context
            ],
            "metadata": {
                "intent": intent,
                "entities": state.get("entities", []),
                "documents_retrieved": len(rag_context),
                "nodes_retrieved": len(graph_context.get("concepts", [])),
                "images_attached": sum(len(n.get("images", [])) for n in rag_context),
            },
        }
        
    except Exception as e:
        logger.error("generate_response_node: Failed", error=str(e))
        return {
            "messages": [AIMessage(content="I encountered an error. Please try again.")],
        }


# ============================================================================
# Routing Function
# ============================================================================


def should_use_tools(state: ChatState) -> Literal["tools", "get_context"]:
    """
    Route based on whether tools should be called.
    
    For now, we skip direct tool usage and go to context retrieval.
    This can be expanded to use tools_condition for more complex flows.
    """
    # In a full implementation, this would check if the LLM requested tools
    # For this refactor, we go straight to context retrieval
    return "get_context"


# ============================================================================
# Graph Builder
# ============================================================================


def create_chat_graph():
    """
    Build the chat workflow graph.
    
    Flow:
    START → analyze_query → get_context → generate_response → END
    
    LangGraph features demonstrated:
    - StateGraph with typed state
    - add_messages reducer for message history
    - Proper message types
    - Checkpointing for persistence
    """
    builder = StateGraph(ChatState)
    
    # Add nodes
    builder.add_node("analyze_query", analyze_query_node)
    builder.add_node("get_context", get_context_node)
    builder.add_node("generate_response", generate_response_node)
    
    # Optional: Add ToolNode for tool-based execution
    # builder.add_node("tools", ToolNode(chat_tools))
    
    # Define edges
    builder.add_edge(START, "analyze_query")
    builder.add_edge("analyze_query", "get_context")
    builder.add_edge("get_context", "generate_response")
    builder.add_edge("generate_response", END)
    
    # Compile with checkpointer for conversation memory
    # Conditional: Skip in LangGraph Studio (it provides its own), use in production
    import sys
    is_langgraph_api = "langgraph_api" in sys.modules
    if is_langgraph_api:
        return builder.compile()
    else:
        checkpointer = get_checkpointer()
        return builder.compile(checkpointer=checkpointer)


# Global graph instance
chat_graph = create_chat_graph()


# ============================================================================
# Public Interface
# ============================================================================


async def run_chat(
    user_id: str,
    message: str,
    thread_id: Optional[str] = None,
    focused_source_ids: Optional[list[str]] = None,  # Source-scoped filtering
) -> dict:
    """
    Run the chat workflow.
    
    Args:
        user_id: User ID
        message: User's message
        thread_id: Optional thread ID for conversation persistence
        focused_source_ids: Optional list of note/concept IDs to scope retrieval to.
                           When provided, chat will ONLY use context from these sources.
    
    Returns:
        Dict with response, sources, and related_concepts
    """
    import uuid
    
    thread_id = thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state: ChatState = {
        "messages": [HumanMessage(content=message)],
        "user_id": user_id,
        "focused_source_ids": focused_source_ids or [],  # Pass to state
        "graph_context": {},
        "rag_context": [],
    }
    
    logger.info(
        "run_chat: Starting",
        user_id=user_id,
        thread_id=thread_id,
        message_length=len(message),
        focused_sources=len(focused_source_ids) if focused_source_ids else 0,
    )
    
    try:
        result = await chat_graph.ainvoke(initial_state, config)
        
        # Extract the last AI message
        messages = result.get("messages", [])
        response_text = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                response_text = msg.content
                break
        
        logger.info("run_chat: Complete", thread_id=thread_id)
        
        return {
            "response": response_text,
            "sources": result.get("sources", []),
            "related_concepts": result.get("related_concepts", []),
            "metadata": result.get("metadata", {}),
            "thread_id": thread_id,
        }
        
    except Exception as e:
        logger.error("run_chat: Failed", error=str(e))
        return {
            "response": "I encountered an error. Please try again.",
            "sources": [],
            "related_concepts": [],
            "metadata": {},
            "thread_id": thread_id,
            "error": str(e),
        }


async def get_chat_history(thread_id: str) -> list[dict]:
    """
    Get conversation history for a thread.
    
    Uses LangGraph's checkpointer to retrieve persisted messages.
    """
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        state = await chat_graph.aget_state(config)
        messages = state.values.get("messages", [])
        
        return [
            {
                "role": "human" if isinstance(m, HumanMessage) else "assistant",
                "content": m.content,
            }
            for m in messages
        ]
        
    except Exception as e:
        logger.error("get_chat_history: Failed", error=str(e))
        return []
