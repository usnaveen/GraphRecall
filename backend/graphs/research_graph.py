"""
LangGraph Research Workflow (ReAct Agent)

Demonstrates the create_react_agent prebuilt pattern for interview:
- Uses LangGraph's prebuilt ReAct agent
- Tool calling with automatic execution loop
- Integrated with Tavily for web search
- Checkpointing for persistence

This is the most interview-ready pattern for showing modern
agentic LLM applications.
"""

import uuid
from typing import Optional

import structlog
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import tool
from backend.config.llm import get_chat_model
from langgraph.prebuilt import create_react_agent

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.graphs.checkpointer import get_checkpointer

# Try to import Tavily (updated to new langchain-tavily package)
try:
    from langchain_tavily import TavilySearch
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False

logger = structlog.get_logger()


# ============================================================================
# Tool Definitions for ReAct Agent
# ============================================================================


@tool
async def search_web(query: str) -> str:
    """
    Search the web for information using Tavily.
    
    Args:
        query: Search query
    
    Returns:
        Search results as formatted string
    """
    logger.info("search_web: Executing", query=query)
    
    if not TAVILY_AVAILABLE:
        return "Web search unavailable. Tavily is not installed."
    
    try:
        tavily = TavilySearch(max_results=5)
        results = await tavily.ainvoke(query)
        
        output = "## Web Search Results:\n\n"
        for r in results:
            output += f"**{r.get('title', 'No title')}**\n"
            output += f"{r.get('content', '')[:400]}...\n"
            output += f"Source: {r.get('url', 'Unknown')}\n\n"
        
        return output
        
    except Exception as e:
        logger.error("search_web: Failed", error=str(e))
        return f"Search failed: {str(e)}"


@tool
async def save_research_note(
    topic: str,
    content: str,
    sources: list[str],
    user_id: str = "default"
) -> str:
    """
    Save research findings as a note in the database.
    
    Args:
        topic: Research topic
        content: Note content
        sources: List of source URLs
        user_id: User ID
    
    Returns:
        Success message with note ID
    """
    logger.info("save_research_note: Saving", topic=topic)
    
    try:
        pg_client = await get_postgres_client()
        
        note_id = str(uuid.uuid4())
        
        # Format sources into content
        sources_text = "\n\n## Sources\n" + "\n".join([f"- {s}" for s in sources])
        full_content = content + sources_text
        
        await pg_client.execute_insert(
            """
            INSERT INTO notes (id, user_id, title, content_text, created_at)
            VALUES (:id, :user_id, :title, :content_text, NOW())
            """,
            {
                "id": note_id,
                "user_id": user_id,
                "title": f"Research: {topic}",
                "content_text": full_content,
            }
        )
        
        logger.info("save_research_note: Complete", note_id=note_id)
        
        return f"Note saved successfully with ID: {note_id}"
        
    except Exception as e:
        logger.error("save_research_note: Failed", error=str(e))
        return f"Failed to save note: {str(e)}"


@tool
async def search_existing_knowledge(topic: str) -> str:
    """
    Search existing notes and concepts before doing web research.
    
    Args:
        topic: Topic to search for
    
    Returns:
        Existing knowledge on this topic
    """
    logger.info("search_existing_knowledge: Searching", topic=topic)
    
    try:
        # Search concepts
        neo4j = await get_neo4j_client()
        concepts = await neo4j.execute_query(
            """
            MATCH (c:Concept)
            WHERE toLower(c.name) CONTAINS toLower($topic)
            RETURN c.name as name, c.definition as definition
            LIMIT 5
            """,
            {"topic": topic}
        )
        
        # Search notes
        pg_client = await get_postgres_client()
        notes = await pg_client.fetch(
            """
            SELECT title, content FROM notes
            WHERE title ILIKE $1 OR content ILIKE $1
            LIMIT 3
            """,
            f"%{topic}%"
        )
        
        output = "## Existing Knowledge:\n\n"
        
        if concepts:
            output += "### Concepts:\n"
            for c in concepts:
                output += f"- **{c['name']}**: {c.get('definition', 'No definition')}\n"
        
        if notes:
            output += "\n### Notes:\n"
            for n in notes:
                output += f"- {n.get('title', 'Untitled')}: {n.get('content', '')[:200]}...\n"
        
        if not concepts and not notes:
            output = f"No existing knowledge found for '{topic}'. Web research recommended."
        
        return output
        
    except Exception as e:
        logger.error("search_existing_knowledge: Failed", error=str(e))
        return f"Search failed: {str(e)}"


# ============================================================================
# ReAct Agent Creation
# ============================================================================


def create_research_agent():
    """
    Create a ReAct agent using LangGraph's prebuilt pattern.
    
    This is the interview-ready way to create tool-using agents.
    
    Features:
    - Automatic tool call → response loop
    - Clean tool integration
    - Checkpointing for state persistence
    """
    # Define available tools
    tools = [
        search_existing_knowledge,
        save_research_note,
    ]
    
    # Add web search if available
    if TAVILY_AVAILABLE:
        tools.append(search_web)
    
    # Create the model (Gemini)
    model = get_chat_model(temperature=0.3)
    
    # System prompt for the research agent
    system_prompt = """You are a research assistant for GraphRecall.

Your job is to help users research topics and save findings as notes.

Follow this workflow:
1. First, use search_existing_knowledge to check if we already have info
2. If knowledge is insufficient, use search_web to find information
3. Synthesize the findings into a clear, educational note
4. Use save_research_note to save the final research

Be thorough but concise. Always cite sources."""

    # Conditional checkpointer: Skip in LangGraph Studio (it provides its own), use in production
    import sys
    is_langgraph_api = "langgraph_api" in sys.modules
    if is_langgraph_api:
        # Running in LangGraph Studio/Cloud - persistence is automatic
        agent = create_react_agent(
            model=model,
            tools=tools,
        )
    else:
        # Local dev or production - use our checkpointer for persistence
        checkpointer = get_checkpointer()
        agent = create_react_agent(
            model=model,
            tools=tools,
            checkpointer=checkpointer,
        )
    
    return agent


# Global agent instance
research_agent = create_research_agent()


# ============================================================================
# Public Interface
# ============================================================================


async def run_research(
    topic: str,
    user_id: str = "default",
    thread_id: Optional[str] = None,
) -> dict:
    """
    Run the research agent workflow.
    
    Args:
        topic: Topic to research
        user_id: User ID
        thread_id: Optional thread for persistence
    
    Returns:
        Dict with research results
    """
    thread_id = thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    logger.info("run_research: Starting", topic=topic, thread_id=thread_id)
    
    try:
        # Create input with user's research request
        # Note: We inject system prompt here since create_react_agent modifier caused issues
        
        system_prompt = """You are a research assistant for GraphRecall.
Your job is to help users research topics and save findings as notes.

Follow this workflow:
1. First, use search_existing_knowledge to check if we already have info
2. If knowledge is insufficient, use search_web to find information
3. Synthesize the findings into a clear, educational note
4. Use save_research_note to save the final research

Be thorough but concise. Always cite sources."""

        input_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Research this topic and save a note: {topic}\n\nUser ID: {user_id}")
        ]
        
        # Run the agent
        result = await research_agent.ainvoke(
            {"messages": input_messages},
            config
        )
        
        # Extract the final response
        messages = result.get("messages", [])
        final_response = ""
        for msg in reversed(messages):
            if hasattr(msg, "content") and not hasattr(msg, "tool_calls"):
                final_response = msg.content
                break
        
        logger.info("run_research: Complete", thread_id=thread_id)
        
        return {
            "topic": topic,
            "response": final_response,
            "thread_id": thread_id,
            "message_count": len(messages),
        }
        
    except Exception as e:
        logger.error("run_research: Failed", error=str(e))
        return {
            "topic": topic,
            "response": f"Research failed: {str(e)}",
            "thread_id": thread_id,
            "error": str(e),
        }


async def get_research_history(thread_id: str) -> list[dict]:
    """
    Get the research conversation history.
    
    Uses checkpointer to retrieve persisted state.
    """
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        state = await research_agent.aget_state(config)
        messages = state.values.get("messages", [])
        
        history = []
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                history.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [tc.get("name") for tc in msg.tool_calls]
                })
            elif hasattr(msg, "content"):
                role = "human" if isinstance(msg, HumanMessage) else "assistant"
                history.append({"role": role, "content": msg.content})
        
        return history
        
    except Exception as e:
        logger.error("get_research_history: Failed", error=str(e))
        return []
