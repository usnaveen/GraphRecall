"""
LangGraph Quiz Generation Workflow

Demonstrates key LangGraph patterns for interview:
- Conditional edges based on resource sufficiency
- @tool decorator for tool definition
- ToolNode for automatic tool execution
- State-based routing

Flow:
START → fetch_resources → check_sufficiency → (conditional)
    → [sufficient] → generate_quiz → END
    → [insufficient] → research → generate_quiz → END
"""

import json
import uuid
from typing import Annotated, Literal, Optional

import structlog
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from backend.config.llm import get_chat_model
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel
from typing_extensions import TypedDict

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.graphs.checkpointer import get_checkpointer

# Try to import Tavily for web search
try:
    from langchain_community.tools.tavily_search import TavilySearchResults
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False

logger = structlog.get_logger()


# ============================================================================
# State Definition
# ============================================================================


class QuizState(TypedDict, total=False):
    """
    State for quiz generation with conditional routing.
    
    Demonstrates how to use state for routing decisions.
    """
    # Input
    topic: str
    user_id: str
    num_questions: int
    
    # User consent for web research (default: False)
    allow_research: bool  # Must be explicitly True to enable web search
    
    # Resources
    resources: list[dict]
    resource_count: int
    
    # Routing
    needs_research: bool
    research_results: list[dict]
    
    # Output
    questions: list[dict]
    
    # Messages for tool calling
    messages: Annotated[list, add_messages]
    
    # Error handling
    error: Optional[str]



# ============================================================================
# Tool Definitions
# ============================================================================


@tool
async def search_knowledge_for_quiz(topic: str) -> str:
    """
    Search the knowledge graph for resources about a quiz topic.
    
    Args:
        topic: The topic to search for quiz content
    
    Returns:
        Formatted string with available resources
    """
    logger.info("search_knowledge_for_quiz: Searching", topic=topic)
    
    try:
        neo4j = await get_neo4j_client()
        
        # Search for concepts related to the topic
        concepts = await neo4j.execute_query(
            """
            MATCH (c:Concept)
            WHERE toLower(c.name) CONTAINS toLower($topic)
               OR toLower(c.definition) CONTAINS toLower($topic)
            RETURN c.id as id, c.name as name, c.definition as definition,
                   c.domain as domain
            LIMIT 10
            """,
            {"topic": topic}
        )
        
        # Search for notes about the topic
        pg_client = await get_postgres_client()
        notes = await pg_client.fetch(
            """
            SELECT id, title, content FROM notes
            WHERE title ILIKE $1 OR content ILIKE $1
            LIMIT 5
            """,
            f"%{topic}%"
        )
        
        output = f"## Resources for '{topic}':\n\n"
        
        if concepts:
            output += "### Concepts:\n"
            for c in concepts:
                output += f"- **{c['name']}**: {c.get('definition', 'No definition')}\n"
        
        if notes:
            output += "\n### Notes:\n"
            for n in notes:
                output += f"- {n.get('title', 'Untitled')}\n"
        
        if not concepts and not notes:
            output = f"No resources found for '{topic}'. Consider researching online."
        
        return output
        
    except Exception as e:
        logger.error("search_knowledge_for_quiz: Failed", error=str(e))
        return f"Error searching: {str(e)}"


@tool
async def web_search_for_topic(query: str) -> str:
    """
    Search the web for information when local knowledge is insufficient.
    
    Uses Tavily search if available, otherwise returns a placeholder.
    
    Args:
        query: Search query for web research
    
    Returns:
        Search results as formatted string
    """
    logger.info("web_search_for_topic: Searching", query=query)
    
    if TAVILY_AVAILABLE:
        try:
            tavily = TavilySearchResults(max_results=3)
            results = await tavily.ainvoke(query)
            
            output = "## Web Research Results:\n\n"
            for r in results:
                output += f"**{r.get('title', 'No title')}**\n"
                output += f"{r.get('content', '')[:300]}...\n"
                output += f"Source: {r.get('url', 'Unknown')}\n\n"
            
            return output
            
        except Exception as e:
            logger.error("web_search: Tavily failed", error=str(e))
            return f"Web search failed: {str(e)}"
    
    else:
        return f"Web search unavailable. Please install langchain-community with Tavily support."


# Tools for ToolNode
quiz_tools = [search_knowledge_for_quiz, web_search_for_topic]


# ============================================================================
# Node Functions
# ============================================================================


async def fetch_resources_node(state: QuizState) -> dict:
    """
    Node 1: Fetch resources from knowledge base for the quiz topic.
    """
    topic = state.get("topic", "")
    user_id = state.get("user_id", "default")
    
    logger.info("fetch_resources_node: Fetching", topic=topic)
    
    resources = []
    
    try:
        # Get concepts
        neo4j = await get_neo4j_client()
        concepts = await neo4j.execute_query(
            """
            MATCH (c:Concept)
            WHERE toLower(c.name) CONTAINS toLower($topic)
               OR toLower(c.definition) CONTAINS toLower($topic)
            RETURN c.id as id, c.name as name, c.definition as definition,
                   c.domain as domain, 'concept' as type
            LIMIT 10
            """,
            {"topic": topic}
        )
        resources.extend(concepts)
        
        # Get notes
        pg_client = await get_postgres_client()
        notes = await pg_client.fetch(
            """
            SELECT id, title, content, 'note' as type FROM notes
            WHERE user_id = $1 AND (title ILIKE $2 OR content ILIKE $2)
            LIMIT 5
            """,
            user_id,
            f"%{topic}%"
        )
        resources.extend([dict(n) for n in notes] if notes else [])
        
    except Exception as e:
        logger.error("fetch_resources_node: Failed", error=str(e))
    
    logger.info("fetch_resources_node: Complete", count=len(resources))
    
    return {
        "resources": resources,
        "resource_count": len(resources),
    }


async def check_sufficiency_node(state: QuizState) -> dict:
    """
    Node 2: Check if resources are sufficient for quiz generation.
    
    This node determines the routing decision.
    """
    resource_count = state.get("resource_count", 0)
    num_questions = state.get("num_questions", 5)
    
    # Need at least 2 resources per question for good quiz
    min_resources = max(3, num_questions // 2)
    needs_research = resource_count < min_resources
    
    logger.info(
        "check_sufficiency_node: Evaluated",
        resource_count=resource_count,
        min_needed=min_resources,
        needs_research=needs_research,
    )
    
    return {"needs_research": needs_research}


async def research_node(state: QuizState) -> dict:
    """
    Node 3a: Conduct web research for insufficient topics.
    
    Called when local resources are insufficient.
    """
    topic = state.get("topic", "")
    
    logger.info("research_node: Researching", topic=topic)
    
    if not TAVILY_AVAILABLE:
        logger.warning("research_node: Tavily not available")
        return {"research_results": []}
    
    try:
        tavily = TavilySearchResults(max_results=5)
        results = await tavily.ainvoke(f"{topic} explained concepts")
        
        research_results = [
            {
                "title": r.get("title", ""),
                "content": r.get("content", ""),
                "url": r.get("url", ""),
            }
            for r in results
        ]
        
        logger.info("research_node: Complete", count=len(research_results))
        
        return {"research_results": research_results}
        
    except Exception as e:
        logger.error("research_node: Failed", error=str(e))
        return {"research_results": []}


async def generate_quiz_node(state: QuizState) -> dict:
    """
    Node 4: Generate quiz questions from available resources.
    
    Uses LLM with structured output for reliable JSON parsing.
    """
    topic = state.get("topic", "")
    resources = state.get("resources", [])
    research_results = state.get("research_results", [])
    num_questions = state.get("num_questions", 5)
    
    logger.info("generate_quiz_node: Generating", topic=topic, num_questions=num_questions)
    
    # Combine all available content
    content_parts = []
    
    for r in resources:
        if r.get("type") == "concept":
            content_parts.append(f"Concept: {r.get('name')} - {r.get('definition', '')}")
        elif r.get("type") == "note":
            content_parts.append(f"Note: {r.get('title', '')} - {r.get('content', '')[:500]}")
    
    for r in research_results:
        content_parts.append(f"Research: {r.get('title', '')} - {r.get('content', '')[:500]}")
    
    combined_content = "\n\n".join(content_parts) if content_parts else f"Topic: {topic}"
    
    # LLM for quiz generation (Gemini)
    llm = get_chat_model(temperature=0.5)
    
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=f"""Generate {num_questions} quiz questions about "{topic}".

Based on this content:
{combined_content[:3000]}

Create varied question types:
- Multiple choice (4 options)
- True/False
- Fill in the blank

Output JSON:
{{
    "questions": [
        {{
            "id": "q1",
            "type": "multiple_choice|true_false|fill_blank",
            "question": "The question text",
            "options": ["A", "B", "C", "D"] or null,
            "correct_answer": "The correct answer",
            "explanation": "Why this is correct"
        }}
    ]
}}"""),
        HumanMessage(content=f"Generate {num_questions} questions about {topic}")
    ])
    
    try:
        response = await llm.ainvoke(prompt.format_messages())
        parsed = json.loads(response.content)
        questions = parsed.get("questions", [])
        
        logger.info("generate_quiz_node: Complete", count=len(questions))
        
        return {"questions": questions}
        
    except Exception as e:
        logger.error("generate_quiz_node: Failed", error=str(e))
        return {"questions": [], "error": str(e)}


# ============================================================================
# Routing Function
# ============================================================================


def route_by_sufficiency(state: QuizState) -> Literal["research", "generate_quiz"]:
    """
    Route based on resource sufficiency AND user consent.
    
    Web research only happens if:
    1. Resources are insufficient (needs_research = True)
    2. User has explicitly consented (allow_research = True)
    
    This prevents unexpected web searches and API costs.
    """
    needs_research = state.get("needs_research", False)
    allow_research = state.get("allow_research", False)  # Default: NO research
    
    if needs_research and allow_research:
        logger.info("route_by_sufficiency: Routing to research (user consented)")
        return "research"
    elif needs_research and not allow_research:
        logger.info("route_by_sufficiency: Skipping research (no user consent, will use available resources)")
        return "generate_quiz"
    else:
        logger.info("route_by_sufficiency: Routing to generate_quiz (sufficient resources)")
        return "generate_quiz"



# ============================================================================
# Graph Builder
# ============================================================================


def create_quiz_graph():
    """
    Build the quiz generation workflow graph.
    
    Flow:
    START → fetch_resources → check_sufficiency → (conditional)
        → [sufficient] → generate_quiz → END
        → [insufficient] → research → generate_quiz → END
    
    LangGraph features demonstrated:
    - Conditional edges with routing function
    - @tool decorator for tool definition
    - State-based routing decisions
    """
    builder = StateGraph(QuizState)
    
    # Add nodes
    builder.add_node("fetch_resources", fetch_resources_node)
    builder.add_node("check_sufficiency", check_sufficiency_node)
    builder.add_node("research", research_node)
    builder.add_node("generate_quiz", generate_quiz_node)
    
    # Linear edges
    builder.add_edge(START, "fetch_resources")
    builder.add_edge("fetch_resources", "check_sufficiency")
    
    # Conditional edge: route based on sufficiency
    builder.add_conditional_edges(
        "check_sufficiency",
        route_by_sufficiency,
        {
            "research": "research",
            "generate_quiz": "generate_quiz",
        }
    )
    
    # Research leads to quiz generation
    builder.add_edge("research", "generate_quiz")
    
    # Quiz generation ends the workflow
    builder.add_edge("generate_quiz", END)
    
    # Compile with checkpointer
    checkpointer = get_checkpointer()
    
    return builder.compile(checkpointer=checkpointer)


# Global graph instance
quiz_graph = create_quiz_graph()


# ============================================================================
# Public Interface
# ============================================================================


async def run_quiz_generation(
    topic: str,
    user_id: str = "default",
    num_questions: int = 5,
    allow_research: bool = False,  # User must explicitly consent to web search
) -> dict:
    """
    Run the quiz generation workflow.
    
    Args:
        topic: Topic to generate quiz about
        user_id: User ID
        num_questions: Number of questions to generate
        allow_research: If True, allows web research when local resources are insufficient.
                       Default is False - quiz will be generated with available resources only.
    
    Returns:
        Dict with questions and metadata
    """
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state: QuizState = {
        "topic": topic,
        "user_id": user_id,
        "num_questions": num_questions,
        "allow_research": allow_research,  # User consent flag
        "resources": [],
        "resource_count": 0,
        "needs_research": False,
        "research_results": [],
        "questions": [],
    }
    
    logger.info(
        "run_quiz_generation: Starting",
        topic=topic,
        num_questions=num_questions,
        allow_research=allow_research,
    )
    
    try:
        result = await quiz_graph.ainvoke(initial_state, config)
        
        logger.info(
            "run_quiz_generation: Complete",
            num_questions=len(result.get("questions", [])),
        )
        
        return {
            "topic": topic,
            "questions": result.get("questions", []),
            "resource_count": result.get("resource_count", 0),
            "researched": result.get("needs_research", False),
            "thread_id": thread_id,
        }
        
    except Exception as e:
        logger.error("run_quiz_generation: Failed", error=str(e))
        return {
            "topic": topic,
            "questions": [],
            "error": str(e),
            "thread_id": thread_id,
        }
