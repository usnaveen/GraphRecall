"""
LangGraph Article Processing Agent (Substack/Blog)

Goal: Fetch URL -> Extract Content/Structure -> Convert to Markdown -> Ingest to Knowledge Graph.
"""

import httpx
from typing import TypedDict, Optional, List
import structlog
from datetime import datetime

from langgraph.graph import StateGraph, START, END
from backend.config.llm import get_chat_model
from backend.graphs.ingestion_graph import run_ingestion
from langchain_core.messages import SystemMessage, HumanMessage

logger = structlog.get_logger()
llm = get_chat_model(temperature=0.1) # Deterministic for structure

# ============================================================================
# State
# ============================================================================

class ArticleState(TypedDict):
    url: str
    user_id: str
    html_content: Optional[str]
    title: Optional[str]
    author: Optional[str]
    markdown_content: Optional[str]
    ingestion_result: Optional[dict]
    error: Optional[str]

# ============================================================================
# Nodes
# ============================================================================

async def fetch_article_node(state: ArticleState) -> dict:
    """Fetch raw HTML from URL."""
    url = state["url"]
    logger.info("fetch_article: Fetching", url=url)
    
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
            return {"html_content": response.text}
    except Exception as e:
        logger.error("fetch_article: Failed", error=str(e))
        return {"error": f"Failed to fetch URL: {str(e)}"}

async def parse_structure_node(state: ArticleState) -> dict:
    """Use Gemini to extract structured content (Title, Author, Markdown)."""
    if state.get("error"):
        return {}
        
    html = state["html_content"]
    # Truncate likely-too-large HTML to safe limits (e.g. 100k chars) 
    # Gemini 1.5 has 1M-2M context, so 100k is safe.
    html_safe = html[:200000] 
    
    prompt = """You are an expert Article Curator.
Analyze the provided HTML content (from a blog or Substack).

Goals:
1. Extract the MAIN Article content (ignore nav, footers, sidebars).
2. Format it as Clean Markdown.
3. Identify Title and Author.
4. Keep Code Blocks intact.

Return VALID JSON:
{
    "title": "Article Title",
    "author": "Author Name",
    "markdown": "# Title\\n\\nBy Author\\n\\n...content..."
}
"""
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=f"HTML Content:\n{html_safe}")
        ])
        
        # Clean JSON
        content = response.content.strip()
        if content.startswith("```json"):
            content = content.split("```json")[1].split("```")[0].strip()
        elif content.startswith("```"):
            content = content.split("```")[1].split("```")[0].strip()
            
        import json
        data = json.loads(content)
        
        return {
            "title": data.get("title"),
            "author": data.get("author"),
            "markdown_content": data.get("markdown")
        }
    except Exception as e:
        logger.error("parse_structure: LLM Failed", error=str(e))
        return {"error": f"Failed to parse article: {str(e)}"}

async def ingest_article_node(state: ArticleState) -> dict:
    """Trigger the main Ingestion Graph."""
    if state.get("error"):
        return {}
        
    markdown = state["markdown_content"]
    title = state.get("title", "Untitled Article")
    user_id = state.get("user_id", "default_user")
    
    # Prefix with explicit attribution source
    full_content = f"Source: {state['url']}\nAuthor: {state.get('author', 'Unknown')}\n\n{markdown}"
    
    try:
        result = await run_ingestion(
            content=full_content,
            title=title,
            user_id=user_id,
            skip_review=True # Auto-ingest for smooth UX, or False if preferred
        )
        return {"ingestion_result": result}
    except Exception as e:
        return {"error": f"Ingestion failed: {str(e)}"}

# ============================================================================
# Graph
# ============================================================================

builder = StateGraph(ArticleState)
builder.add_node("fetch", fetch_article_node)
builder.add_node("parse", parse_structure_node)
builder.add_node("ingest", ingest_article_node)

builder.add_edge(START, "fetch")
builder.add_edge("fetch", "parse")
builder.add_edge("parse", "ingest")
builder.add_edge("ingest", END)

article_graph = builder.compile()

async def process_article_url(url: str, user_id: str = "default_user") -> dict:
    """Entry point for API."""
    initial = {
        "url": url,
        "user_id": user_id,
        "html_content": None,
        "markdown_content": None,
        "error": None
    }
    return await article_graph.ainvoke(initial)
