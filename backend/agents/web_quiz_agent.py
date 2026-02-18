import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import structlog
from langchain_core.messages import SystemMessage, HumanMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config.llm import get_chat_model
from backend.db.postgres_client import get_postgres_client
from backend.models.feed_schemas import MCQQuestion, MCQOption

logger = structlog.get_logger()

# Optional dependency: keep server startup resilient when Tavily is absent.
try:
    from langchain_tavily import TavilySearch
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False

class WebQuizAgent:
    """
    Agent that searches the web for quiz/interview questions 
    and converts them into structured MCQs.
    """
    
    def __init__(self):
        self.llm = get_chat_model(temperature=0.2, json_mode=True)
        # Initialize search tool - expects TAVILY_API_KEY in env
        if not TAVILY_AVAILABLE:
            logger.warning("WebQuizAgent: langchain_tavily not installed, web search disabled")
            self.search = None
            return

        try:
            self.search = TavilySearch(max_results=3)
        except Exception as e:
            logger.warning("WebQuizAgent: Tavily not configured", error=str(e))
            self.search = None

    async def _get_cached_search(self, query: str) -> Optional[List[dict]]:
        """Check if search query is cached."""
        try:
            pg_client = await get_postgres_client()
            query_hash = hashlib.sha256(query.encode()).hexdigest()
            
            result = await pg_client.execute_query(
                """
                SELECT results_json, created_at 
                FROM web_search_cache 
                WHERE query_hash = :hash
                """,
                {"hash": query_hash}
            )
            
            if result:
                # Check TTL (e.g. 7 days)
                created_at = result[0]["created_at"]
                if (datetime.now(created_at.tzinfo) - created_at).days < 7:
                    return result[0]["results_json"]
            return None
        except Exception as e:
            logger.warning("WebQuizAgent: Cache lookup failed", error=str(e))
            return None

    async def _cache_search(self, query: str, results: List[dict]):
        """Cache search results."""
        try:
            pg_client = await get_postgres_client()
            query_hash = hashlib.sha256(query.encode()).hexdigest()
            
            await pg_client.execute_insert(
                """
                INSERT INTO web_search_cache (query_hash, query_text, results_json)
                VALUES (:hash, :text, :json)
                ON CONFLICT (query_hash) 
                DO UPDATE SET results_json = :json, created_at = CURRENT_TIMESTAMP
                """,
                {
                    "hash": query_hash,
                    "text": query,
                    "json": json.dumps(results)
                }
            )
        except Exception as e:
            logger.warning("WebQuizAgent: Cache save failed", error=str(e))

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def find_quizzes(
        self, 
        concept_name: str, 
        domain: str = "General",
        num_questions: int = 3
    ) -> Tuple[List[MCQQuestion], str]:
        """
        Search the web for questions about a concept and parse them.
        Returns: (List[MCQQuestion], source_url)
        """
        if not self.search:
            logger.warning("WebQuizAgent: Search disabled (no API key?)")
            return [], ""

        logger.info("WebQuizAgent: Searching", concept=concept_name)
        
        try:
            # 1. Search for content (Check Cache First)
            query = f"interview questions multiple choice {concept_name} {domain} practice quiz"
            
            search_results = await self._get_cached_search(query)
            if search_results:
                logger.info("WebQuizAgent: CACHE HIT for query", query=query)
            else:
                search_results = await self.search.ainvoke(query)
                # Cache the results
                await self._cache_search(query, search_results)
            
            # Format context from search results
            context_text = "\n\n".join([
                f"Source: {res['url']}\nContent: {res['content']}" 
                for res in search_results
            ])
            
            # Use the first result as the primary source URL (simplification)
            primary_source_url = search_results[0]['url'] if search_results else ""
            
            if not context_text:
                return [], ""

            # 2. Extract/Generate MCQs using LLM (Code unchanged below)
            prompt = f"""You are a Quiz Generator Agent.
Your task is to create {num_questions} high-quality Multiple Choice Questions (MCQs) about '{concept_name}' using the provided search results.

SEARCH RESULTS:
{context_text}

REQUIREMENTS:
1. Generate exactly {num_questions} questions.
2. Use the search results to ensure factual accuracy.
3. If search results lack direct questions, synthesize them from the facts found.
4. Each question must have exactly 4 options.
5. Provide a clear explanation for the correct answer.

OUTPUT JSON FORMAT:
{{
    "quizzes": [
        {{
            "question": "Question text...",
            "options": [
                {{"id": "A", "text": "Option A", "is_correct": false}},
                {{"id": "B", "text": "Option B", "is_correct": true}},
                {{"id": "C", "text": "Option C", "is_correct": false}},
                {{"id": "D", "text": "Option D", "is_correct": false}}
            ],
            "explanation": "Why B is correct...",
            "difficulty": 5
        }}
    ]
}}"""

            response = await self.llm.ainvoke(prompt)
            content = response.content
            
            # Parse JSON with robustness
            clean_content = content
            if "```json" in content:
                clean_content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                clean_content = content.split("```")[1].split("```")[0].strip()
            
            # Fix potential backslash issues (common in LLM output)
            import re
            clean_content = re.sub(r'\\(?!["\\bfnrtu/])', r'\\\\', clean_content)
                
            data = json.loads(clean_content)
            quizzes_data = data.get("quizzes", [])
            
            # Convert to schema
            mcqs = []
            for q in quizzes_data:
                options = []
                for o in q["options"]:
                    if isinstance(o, dict):
                         options.append(MCQOption(id=o.get("id", "A"), text=o.get("text", ""), is_correct=o.get("is_correct", False)))
                    elif isinstance(o, str):
                        # Fallback for malformed output (just string options)
                        # We can't know which is correct, so default to False or skip
                        # Here we give it a dummy ID and assume false
                        options.append(MCQOption(id="?", text=o, is_correct=False))
                # Create MCQQuestion with the processed options list
                mcqs.append(MCQQuestion(
                    concept_id="", # Caller handles this
                    question=q["question"],
                    options=options,
                    explanation=q.get("explanation", ""),
                    difficulty=q.get("difficulty", 5)
                ))
                
            logger.info("WebQuizAgent: Found/Generated quizzes", count=len(mcqs))
            return mcqs, primary_source_url

        except Exception as e:
            logger.error("WebQuizAgent: Failed to generate quizzes", error=str(e))
            return [], ""
