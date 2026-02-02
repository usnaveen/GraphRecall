"""Agent for sourcing quiz content from the web when local content is exhausted."""

import json
import os
from typing import List, Optional

import structlog
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.messages import SystemMessage, HumanMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config.llm import get_chat_model
from backend.models.feed_schemas import MCQQuestion, MCQOption

logger = structlog.get_logger()

class WebQuizAgent:
    """
    Agent that searches the web for quiz/interview questions 
    and converts them into structured MCQs.
    """
    
    def __init__(self):
        self.llm = get_chat_model(temperature=0.2, json_mode=True)
        # Initialize search tool - expects TAVILY_API_KEY in env
        try:
            self.search = TavilySearchResults(max_results=3)
        except Exception as e:
            logger.warning("WebQuizAgent: Tavily not configured", error=str(e))
            self.search = None

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def find_quizzes(
        self, 
        concept_name: str, 
        domain: str = "General",
        num_questions: int = 3
    ) -> List[MCQQuestion]:
        """
        Search the web for questions about a concept and parse them.
        """
        if not self.search:
            logger.warning("WebQuizAgent: Search disabled (no API key?)")
            return []

        logger.info("WebQuizAgent: Searching", concept=concept_name)
        
        try:
            # 1. Search for content
            query = f"interview questions multiple choice {concept_name} {domain} practice quiz"
            search_results = await self.search.ainvoke(query)
            
            # Format context from search results
            context_text = "\n\n".join([
                f"Source: {res['url']}\nContent: {res['content']}" 
                for res in search_results
            ])
            
            if not context_text:
                return []

            # 2. Extract/Generate MCQs using LLM
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
            
            # Parse JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            data = json.loads(content)
            quizzes_data = data.get("quizzes", [])
            
            # Convert to schema
            mcqs = []
            for q in quizzes_data:
                options = [
                    MCQOption(id=o["id"], text=o["text"], is_correct=o["is_correct"]) 
                    for o in q["options"]
                ]
                mcqs.append(MCQQuestion(
                    concept_id="", # Caller handles this
                    question=q["question"],
                    options=options,
                    explanation=q.get("explanation", ""),
                    difficulty=q.get("difficulty", 5)
                ))
                
            logger.info("WebQuizAgent: Found/Generated quizzes", count=len(mcqs))
            return mcqs

        except Exception as e:
            logger.error("WebQuizAgent: Failed to generate quizzes", error=str(e))
            return []
