"""Agent 1: Extraction Agent - Extracts concepts from input content."""

import json
import time
from pathlib import Path
from typing import Optional

import structlog
from backend.config.llm import get_chat_model
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.models.schemas import ConceptCreate, ExtractionResult

logger = structlog.get_logger()

# Load the extraction prompt template
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extraction.txt"


class ExtractionAgent:
    """
    Agent 1: Concept Extraction Agent.

    Uses GPT-3.5-turbo to extract concepts, definitions, and relationships
    from markdown/text content. Optimized for cost and speed.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.1,
    ):
        self.model_name = model
        self.llm = get_chat_model(
            model=model,
            temperature=temperature,
            json_mode=True,
        )
        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load the extraction prompt template from file."""
        try:
            return PROMPT_PATH.read_text()
        except FileNotFoundError:
            logger.warning("Extraction prompt file not found, using default")
            return self._default_prompt()

    def _default_prompt(self) -> str:
        """Default extraction prompt if file not found."""
        return """You are a concept extraction expert. Extract key concepts from the following content.

Output JSON format:
{
  "concepts": [
    {
      "name": "Concept Name",
      "definition": "Brief definition",
      "domain": "Subject area",
      "complexity_score": 5,
      "confidence": 0.9,
      "related_concepts": [],
      "prerequisites": []
    }
  ]
}

Content:
{content}"""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def extract(self, content: str) -> ExtractionResult:
        """
        Extract concepts from the input content.

        Args:
            content: The markdown/text content to analyze

        Returns:
            ExtractionResult with list of extracted concepts
        """
        start_time = time.time()

        logger.info(
            "ExtractionAgent: Starting extraction",
            content_length=len(content),
            model=self.model_name,
        )

        # Prepare the prompt
        prompt = self._prompt_template.replace("{content}", content)

        try:
            # Call the LLM
            response = await self.llm.ainvoke(prompt)
            # Clean markdown code blocks from response
            raw_response = response.content.strip()
            if raw_response.startswith("```json"):
                raw_response = raw_response.split("```json")[1].split("```")[0].strip()
            elif raw_response.startswith("```"):
                raw_response = raw_response.split("```")[1].split("```")[0].strip()

            # Parse the JSON response
            parsed = json.loads(raw_response)

            # Convert to ConceptCreate objects
            concepts = []
            for c in parsed.get("concepts", []):
                try:
                    concept = ConceptCreate(
                        name=c.get("name", "Unknown"),
                        definition=c.get("definition", ""),
                        domain=c.get("domain", "General"),
                        complexity_score=float(c.get("complexity_score", 5)),
                        confidence=float(c.get("confidence", 0.8)),
                        related_concepts=c.get("related_concepts", []),
                        prerequisites=c.get("prerequisites", []),
                    )
                    concepts.append(concept)
                except Exception as e:
                    logger.warning(
                        "ExtractionAgent: Failed to parse concept",
                        concept=c,
                        error=str(e),
                    )

            processing_time = (time.time() - start_time) * 1000

            logger.info(
                "ExtractionAgent: Extraction complete",
                num_concepts=len(concepts),
                processing_time_ms=processing_time,
            )

            return ExtractionResult(
                concepts=concepts,
                raw_response=raw_response,
                model_used=self.model_name or "gemini-2.5-flash",
                processing_time_ms=processing_time,
            )

        except json.JSONDecodeError as e:
            logger.error(
                "ExtractionAgent: Failed to parse JSON response",
                error=str(e),
                response=raw_response[:500] if raw_response else None,
            )
            raise ValueError(f"LLM returned invalid JSON: {e}")

        except Exception as e:
            logger.error("ExtractionAgent: Extraction failed", error=str(e))
            raise

    async def extract_with_context(
        self,
        content: str,
        existing_concepts: list[str],
    ) -> ExtractionResult:
        """
        Extract concepts with awareness of existing concepts.

        This helps the agent identify relationships with known concepts
        and avoid duplicating existing knowledge.

        Args:
            content: The markdown/text content to analyze
            existing_concepts: List of concept names already in the graph

        Returns:
            ExtractionResult with list of extracted concepts
        """
        # Append context to the prompt
        context = f"\n\nExisting concepts in the knowledge graph: {', '.join(existing_concepts[:50])}\n\nIdentify relationships with these existing concepts where applicable."

        augmented_content = content + context
        return await self.extract(augmented_content)
