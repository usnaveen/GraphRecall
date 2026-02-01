"""Web Research Agent - Searches the web to create notes when resources are insufficient.

This agent:
1. Detects when a topic has insufficient resources
2. Searches the web using Tavily for quality content
3. Synthesizes findings into structured notes
4. Saves notes and links to concepts
"""

import json
import uuid
from datetime import datetime
from typing import Optional

import structlog
from backend.config.llm import get_chat_model
from pydantic import BaseModel

logger = structlog.get_logger()

# Try to import Tavily, fall back to web search simulation
try:
    from langchain_community.tools.tavily_search import TavilySearchResults
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False
    logger.warning("Tavily not available, will use simulated search")


class ResearchResult(BaseModel):
    """Result from web research."""
    topic: str
    summary: str
    key_points: list[str]
    sources: list[dict]
    note_content: str


class WebResearchAgent:
    """
    Agent that searches the web to create quality notes on topics.
    
    Used when:
    - User searches a topic with insufficient resources
    - Quiz generation needs more content
    - User explicitly asks to research something
    """
    
    def __init__(
        self,
        neo4j_client,
        pg_client,
        model: str = "gpt-4o-mini",
        max_results: int = 5,
    ):
        self.neo4j_client = neo4j_client
        self.pg_client = pg_client
        self.max_results = max_results
        
        self.llm = get_chat_model(temperature=0.3)
        self.synthesizer = get_chat_model(temperature=0.2)
        
        # Initialize search tool
        if TAVILY_AVAILABLE:
            self.search_tool = TavilySearchResults(max_results=max_results)
        else:
            self.search_tool = None
    
    async def check_resources_sufficient(
        self,
        topic_name: str,
        min_resources: int = 3,
    ) -> tuple[bool, list[dict]]:
        """
        Check if a topic has sufficient resources for quiz generation.
        
        Returns:
            Tuple of (is_sufficient, existing_resources)
        """
        try:
            # Get notes linked to this concept
            notes_query = """
            SELECT n.id, n.title, n.content_text, n.resource_type
            FROM notes n
            JOIN proficiency_scores ps ON ps.user_id = n.user_id
            WHERE n.content_text ILIKE :topic_pattern
            LIMIT 10
            """
            
            notes = await self.pg_client.execute_query(
                notes_query,
                {"topic_pattern": f"%{topic_name}%"},
            )
            
            # Get concepts from Neo4j
            concepts_query = """
            MATCH (c:Concept)
            WHERE toLower(c.name) CONTAINS toLower($topic)
            OPTIONAL MATCH (n:NoteSource)-[:EXPLAINS]->(c)
            RETURN c.id as concept_id, c.name as name, 
                   collect(n.id) as linked_notes
            LIMIT 5
            """
            
            concepts = await self.neo4j_client.execute_query(
                concepts_query,
                {"topic": topic_name},
            )
            
            total_resources = len(notes) + len(concepts)
            is_sufficient = total_resources >= min_resources
            
            resources = [
                {"type": "note", **n} for n in notes
            ] + [
                {"type": "concept", **c} for c in concepts
            ]
            
            logger.info(
                "check_resources_sufficient",
                topic=topic_name,
                num_resources=total_resources,
                is_sufficient=is_sufficient,
            )
            
            return is_sufficient, resources
            
        except Exception as e:
            logger.error("check_resources_sufficient failed", error=str(e))
            return False, []
    
    async def search_web(self, query: str) -> list[dict]:
        """
        Search the web for information on a topic.
        
        Returns:
            List of search results with url, title, content
        """
        if not self.search_tool:
            # Simulate search for development
            logger.warning("Using simulated search (Tavily not configured)")
            return [{
                "url": f"https://example.com/{query.replace(' ', '-')}",
                "title": f"About {query}",
                "content": f"This is simulated content about {query}. "
                          f"In production, this would be real web content.",
            }]
        
        try:
            results = await self.search_tool.ainvoke(query)
            
            # Normalize results
            normalized = []
            for r in results:
                if isinstance(r, dict):
                    normalized.append({
                        "url": r.get("url", ""),
                        "title": r.get("title", ""),
                        "content": r.get("content", r.get("snippet", "")),
                    })
            
            logger.info("search_web", query=query, num_results=len(normalized))
            return normalized
            
        except Exception as e:
            logger.error("search_web failed", error=str(e))
            return []
    
    async def synthesize_notes(
        self,
        topic: str,
        search_results: list[dict],
    ) -> ResearchResult:
        """
        Synthesize search results into structured notes.
        
        Creates:
        - Summary of the topic
        - Key points for flashcards
        - Full note content with citations
        """
        # Prepare search content
        sources_text = "\n\n".join([
            f"Source: {r['title']}\nURL: {r['url']}\nContent: {r['content'][:1000]}"
            for r in search_results[:5]
        ])
        
        prompt = f"""You are a knowledge synthesis expert creating study notes.

TOPIC: {topic}

WEB RESEARCH RESULTS:
{sources_text}

Create comprehensive study notes from this research.

Return JSON:
{{
    "summary": "2-3 sentence overview of the topic",
    "key_points": [
        "Important point 1 for flashcard generation",
        "Important point 2",
        "Important point 3"
    ],
    "note_content": "Full markdown notes with sections, examples, and key concepts. Include citations like [1], [2] referencing sources.",
    "definitions": [
        {{"term": "Key Term", "definition": "Clear definition"}}
    ]
}}"""
        
        try:
            response = await self.synthesizer.ainvoke(prompt)
            content = response.content.strip()
            
            # Handle markdown code blocks
            if content.startswith("```json"):
                content = content.split("```json")[1].split("```")[0].strip()
            elif content.startswith("```"):
                content = content.split("```")[1].split("```")[0].strip()
            
            data = json.loads(content)
            
            return ResearchResult(
                topic=topic,
                summary=data.get("summary", ""),
                key_points=data.get("key_points", []),
                sources=[
                    {"url": r["url"], "title": r["title"]}
                    for r in search_results[:5]
                ],
                note_content=data.get("note_content", ""),
            )
            
        except Exception as e:
            logger.error("synthesize_notes failed", error=str(e))
            return ResearchResult(
                topic=topic,
                summary=f"Research on {topic}",
                key_points=[],
                sources=[],
                note_content=f"# {topic}\n\nResearch synthesis failed.",
            )
    
    async def save_research_note(
        self,
        result: ResearchResult,
        user_id: str,
    ) -> str:
        """
        Save the research result as a note in the database.
        
        Returns:
            The created note ID
        """
        note_id = str(uuid.uuid4())
        
        # Add source citations to content
        content_with_sources = result.note_content
        if result.sources:
            content_with_sources += "\n\n## Sources\n"
            for i, source in enumerate(result.sources, 1):
                content_with_sources += f"\n[{i}] [{source['title']}]({source['url']})"
        
        try:
            await self.pg_client.execute_insert(
                """
                INSERT INTO notes (id, user_id, title, content_text, resource_type, tags)
                VALUES (:id, :user_id, :title, :content_text, :resource_type, :tags)
                """,
                {
                    "id": note_id,
                    "user_id": user_id,
                    "title": f"Research: {result.topic}",
                    "content_text": content_with_sources,
                    "resource_type": "research",
                    "tags": result.key_points[:5],
                }
            )
            
            logger.info("save_research_note", note_id=note_id, topic=result.topic)
            return note_id
            
        except Exception as e:
            logger.error("save_research_note failed", error=str(e))
            return ""
    
    async def research_topic(
        self,
        topic: str,
        user_id: str,
        force: bool = False,
    ) -> dict:
        """
        Main research method - checks resources and conducts research if needed.
        
        Args:
            topic: Topic to research
            user_id: User ID
            force: If True, research even if resources are sufficient
        
        Returns:
            Dict with research results and created note ID
        """
        logger.info("research_topic", topic=topic, user_id=user_id, force=force)
        
        # Check existing resources
        is_sufficient, existing = await self.check_resources_sufficient(topic)
        
        if is_sufficient and not force:
            return {
                "status": "sufficient",
                "message": f"Found {len(existing)} existing resources for {topic}",
                "resources": existing,
                "researched": False,
            }
        
        # Search the web
        search_query = f"{topic} explained tutorial guide"
        search_results = await self.search_web(search_query)
        
        if not search_results:
            return {
                "status": "no_results",
                "message": f"No web results found for {topic}",
                "resources": existing,
                "researched": False,
            }
        
        # Synthesize into notes
        result = await self.synthesize_notes(topic, search_results)
        
        # Save the note
        note_id = await self.save_research_note(result, user_id)
        
        return {
            "status": "researched",
            "message": f"Created research notes for {topic}",
            "note_id": note_id,
            "summary": result.summary,
            "key_points": result.key_points,
            "sources": result.sources,
            "researched": True,
        }
