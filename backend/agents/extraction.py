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

    Uses Gemini to extract concepts, definitions, and relationships
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

        # Safety: Truncate content to prevent token limits
        # gemini-2.5-flash has 1M token limit, but let's be safe with 100k chars for now
        # to avoid timeouts/memory issues until we implement chunking
        MAX_CHARS = 100_000
        if len(content) > MAX_CHARS:
            logger.warning(
                "ExtractionAgent: Content too long, truncating",
                original_length=len(content),
                new_length=MAX_CHARS,
            )
            content = content[:MAX_CHARS] + "\n...[TRUNCATED]..."

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
                        evidence_span=c.get("evidence_span"),
                        related_concepts=c.get("related_concepts", []),
                        prerequisites=c.get("prerequisites", []),
                        parent_topic=c.get("parent_topic"),
                        subtopics=c.get("subtopics", []),
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
        concept_list = ", ".join(existing_concepts[:100])
        context = (
            f"\n\nExisting concepts already in the knowledge graph:\n{concept_list}\n\n"
            "IMPORTANT: Do NOT re-extract concepts that already exist above. "
            "Instead, reference them in related_concepts or prerequisites. "
            "If you find a concept that is essentially the same as an existing one "
            "(even with slightly different wording), use the EXISTING name exactly."
        )

        augmented_content = content + context
        return await self.extract(augmented_content)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def consolidate_relationships(
        self,
        all_concepts: list[ConceptCreate],
        book_title: str = "",
    ) -> list[dict]:
        """
        Second pass: Discover cross-chunk relationships between all extracted concepts.

        Inspired by the Microsoft GraphRAG approach — after extracting concepts from
        individual chunks, run a consolidation pass over the full concept list to find
        relationships that span chunk boundaries.

        Args:
            all_concepts: All concepts extracted across all chunks
            book_title: Title of the source book for context

        Returns:
            List of relationship dicts: {from_concept, to_concept, type, reason}
            type is one of: RELATED_TO, PREREQUISITE_OF, SUBTOPIC_OF, PART_OF, BUILDS_ON
        """
        import time

        start_time = time.time()

        # Build a summary of all concepts (names + short definitions)
        concept_summaries = []
        for c in all_concepts[:100]:  # Limit to 100 concepts to fit context
            concept_summaries.append(f"- {c.name}: {c.definition[:120]}")
        concepts_text = "\n".join(concept_summaries)

        prompt = f"""You are a knowledge graph relationship expert. Given the following list of concepts extracted from "{book_title}", discover relationships BETWEEN them that may not have been captured during per-chunk extraction.

Focus on:
1. **PREREQUISITE_OF**: Concept A must be understood before Concept B
2. **SUBTOPIC_OF**: Concept A is a narrower specialization of Concept B
3. **PART_OF**: Concept A is a component/element of Concept B
4. **BUILDS_ON**: Concept A extends or evolves from Concept B
5. **RELATED_TO**: Concepts that are semantically related but not hierarchical

## Concepts:
{concepts_text}

## Guidelines:
- Look for relationships that CROSS topic boundaries (e.g., a concept from Chapter 3 prerequisite for Chapter 7)
- Identify hierarchical structure: which concepts are parents/children of others
- Do NOT repeat relationships that are already obvious from the concept definitions
- Focus on non-obvious, high-value connections
- Return at most 50 relationships

## Output Format:
Return a JSON object:
{{
  "relationships": [
    {{
      "from_concept": "Concept A Name",
      "to_concept": "Concept B Name",
      "type": "PREREQUISITE_OF",
      "reason": "Brief explanation of why this relationship exists"
    }}
  ]
}}
"""

        try:
            response = await self.llm.ainvoke(prompt)
            raw_response = response.content.strip()
            if raw_response.startswith("```json"):
                raw_response = raw_response.split("```json")[1].split("```")[0].strip()
            elif raw_response.startswith("```"):
                raw_response = raw_response.split("```")[1].split("```")[0].strip()

            parsed = json.loads(raw_response)
            relationships = parsed.get("relationships", [])

            processing_time = (time.time() - start_time) * 1000
            logger.info(
                "ExtractionAgent: Consolidation complete",
                num_relationships=len(relationships),
                processing_time_ms=processing_time,
            )

            return relationships

        except json.JSONDecodeError as e:
            logger.error(
                "ExtractionAgent: Failed to parse consolidation JSON",
                error=str(e),
            )
            return []
        except Exception as e:
            logger.error("ExtractionAgent: Consolidation failed", error=str(e))
            return []
