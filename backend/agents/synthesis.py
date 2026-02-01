"""Agent 2: Synthesis Agent - Detects conflicts and merges concepts."""

import json
import time
from pathlib import Path
from typing import Any, Optional

import structlog
from backend.config.llm import get_chat_model, get_embeddings
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.models.schemas import (
    Concept,
    Conflict,
    ConflictDecision,
    MergeStrategy,
    SynthesisResult,
)

logger = structlog.get_logger()

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "synthesis.txt"


class SynthesisAgent:
    """
    Agent 2: Knowledge Synthesis Agent.

    Compares newly extracted concepts against existing knowledge
    to detect duplicates, conflicts, and enhancement opportunities.

    Uses embeddings for initial similarity matching, then LLM for
    detailed analysis.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        embedding_model: str = "models/text-embedding-004",
        similarity_threshold: float = 0.8,
    ):
        self.model_name = model
        self.similarity_threshold = similarity_threshold

        self.llm = get_chat_model(
            model=model,
            temperature=0.1,
            json_mode=True,
        )

        self.embeddings = get_embeddings()

        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load the synthesis prompt template from file."""
        try:
            return PROMPT_PATH.read_text()
        except FileNotFoundError:
            logger.warning("Synthesis prompt file not found, using default")
            return self._default_prompt()

    def _default_prompt(self) -> str:
        """Default synthesis prompt if file not found."""
        return """Analyze these concepts for conflicts and duplicates.

New Concepts:
{new_concepts}

Existing Similar Concepts:
{existing_concepts}

Output JSON:
{
  "decisions": [
    {
      "new_concept_name": "...",
      "decision": "DUPLICATE|CONFLICT|ENHANCE|NEW",
      "confidence": 0.85,
      "matched_concept_id": "...",
      "reasoning": "...",
      "merge_strategy": "SKIP|MERGE|FLAG_FOR_REVIEW|CREATE_NEW",
      "updated_definition": "..."
    }
  ]
}"""

    async def _get_embedding(self, text: str) -> list[float]:
        """Get embedding vector for text."""
        return await self.embeddings.aembed_query(text)

    async def _embed_existing_concepts(
        self,
        existing_concepts: list[dict],
    ) -> list[tuple[dict, list[float]]]:
        """Batch-embed all existing concepts once (cached across new concepts)."""
        texts = [
            f"{c.get('name', '')}: {c.get('definition', '')}"
            for c in existing_concepts
        ]
        # Use batch embed to avoid N sequential API calls
        vectors = await self.embeddings.aembed_documents(texts)
        return list(zip(existing_concepts, vectors))

    async def _find_similar_concepts(
        self,
        concept: dict,
        existing_with_embeddings: list[tuple[dict, list[float]]],
    ) -> list[dict]:
        """
        Find existing concepts similar to the new concept.

        Uses cosine similarity between embeddings to find matches.
        Expects pre-computed existing embeddings from _embed_existing_concepts.
        """
        if not existing_with_embeddings:
            return []

        # Get embedding for the new concept
        concept_text = f"{concept.get('name', '')}: {concept.get('definition', '')}"
        new_embedding = await self._get_embedding(concept_text)

        similar = []
        for existing, existing_embedding in existing_with_embeddings:
            similarity = self._cosine_similarity(new_embedding, existing_embedding)

            if similarity > 0.3:  # Lower threshold for candidates
                similar.append({
                    **existing,
                    "similarity": similarity,
                })

        # Sort by similarity and return top matches
        similar.sort(key=lambda x: x["similarity"], reverse=True)
        return similar[:5]

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import math

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    async def analyze(
        self,
        new_concepts: list[dict],
        existing_concepts: Optional[list[dict]] = None,
    ) -> SynthesisResult:
        """
        Analyze new concepts for conflicts with existing knowledge.

        Args:
            new_concepts: List of newly extracted concepts
            existing_concepts: Optional list of existing concepts to compare against

        Returns:
            SynthesisResult with decisions for each concept
        """
        start_time = time.time()

        logger.info(
            "SynthesisAgent: Starting analysis",
            num_new_concepts=len(new_concepts),
            num_existing=len(existing_concepts) if existing_concepts else 0,
        )

        # If no existing concepts, all are NEW
        if not existing_concepts:
            decisions = [
                Conflict(
                    new_concept_name=c.get("name", "Unknown"),
                    decision=ConflictDecision.NEW,
                    confidence=1.0,
                    matched_concept_id=None,
                    reasoning="No existing concepts to compare against",
                    merge_strategy=MergeStrategy.CREATE_NEW,
                    updated_definition=None,
                )
                for c in new_concepts
            ]

            return SynthesisResult(decisions=decisions)

        # Pre-compute embeddings for existing concepts once (saves N*M -> N+M calls)
        existing_with_embeddings = await self._embed_existing_concepts(existing_concepts)

        # For each new concept, find similar existing concepts
        all_decisions = []

        for concept in new_concepts:
            try:
                similar = await self._find_similar_concepts(concept, existing_with_embeddings)

                if not similar:
                    # No similar concepts found - it's NEW
                    all_decisions.append(
                        Conflict(
                            new_concept_name=concept.get("name", "Unknown"),
                            decision=ConflictDecision.NEW,
                            confidence=1.0,
                            matched_concept_id=None,
                            reasoning="No similar existing concepts found",
                            merge_strategy=MergeStrategy.CREATE_NEW,
                            updated_definition=None,
                        )
                    )
                    continue

                # Use LLM to analyze the match
                decision = await self._analyze_match(concept, similar)
                all_decisions.append(decision)

            except Exception as e:
                logger.warning(
                    "SynthesisAgent: Error analyzing concept",
                    concept=concept.get("name"),
                    error=str(e),
                )
                # Default to NEW on error
                all_decisions.append(
                    Conflict(
                        new_concept_name=concept.get("name", "Unknown"),
                        decision=ConflictDecision.NEW,
                        confidence=0.5,
                        matched_concept_id=None,
                        reasoning=f"Analysis error: {str(e)}",
                        merge_strategy=MergeStrategy.CREATE_NEW,
                        updated_definition=None,
                    )
                )

        processing_time = (time.time() - start_time) * 1000

        logger.info(
            "SynthesisAgent: Analysis complete",
            num_decisions=len(all_decisions),
            processing_time_ms=processing_time,
        )

        return SynthesisResult(decisions=all_decisions)

    async def _analyze_match(
        self,
        new_concept: dict,
        similar_concepts: list[dict],
    ) -> Conflict:
        """
        Use LLM to analyze the match between new and existing concepts.
        """
        # Format for the prompt
        new_str = json.dumps(new_concept, indent=2)
        existing_str = json.dumps(similar_concepts, indent=2)

        prompt = self._prompt_template.replace("{new_concepts}", new_str)
        prompt = prompt.replace("{existing_concepts}", existing_str)

        try:
            response = await self.llm.ainvoke(prompt)
            # Clean markdown code blocks from response
            raw_response = response.content.strip()
            if not raw_response:
                 raise ValueError("Empty LLM response")
                 
            if raw_response.startswith("```json"):
                raw_response = raw_response.split("```json")[1].split("```")[0].strip()
            elif raw_response.startswith("```"):
                raw_response = raw_response.split("```")[1].split("```")[0].strip()

            parsed = json.loads(raw_response)

            decisions = parsed.get("decisions", [])
            if decisions:
                d = decisions[0]
                return Conflict(
                    new_concept_name=d.get("new_concept_name", new_concept.get("name")),
                    decision=ConflictDecision(d.get("decision", "NEW")),
                    confidence=float(d.get("confidence", 0.8)),
                    matched_concept_id=d.get("matched_concept_id"),
                    reasoning=d.get("reasoning", ""),
                    merge_strategy=MergeStrategy(d.get("merge_strategy", "CREATE_NEW")),
                    updated_definition=d.get("updated_definition"),
                )

        except Exception as e:
            logger.warning(
                "SynthesisAgent: LLM analysis failed",
                error=str(e),
            )

        # Default decision based on similarity
        top_match = similar_concepts[0]
        similarity = top_match.get("similarity", 0)

        if similarity > 0.95:
            decision = ConflictDecision.DUPLICATE
            strategy = MergeStrategy.SKIP
        elif similarity > 0.8:
            decision = ConflictDecision.ENHANCE
            strategy = MergeStrategy.MERGE
        else:
            decision = ConflictDecision.NEW
            strategy = MergeStrategy.CREATE_NEW

        return Conflict(
            new_concept_name=new_concept.get("name", "Unknown"),
            decision=decision,
            confidence=similarity,
            matched_concept_id=top_match.get("id"),
            reasoning=f"Similarity score: {similarity:.2f}",
            merge_strategy=strategy,
            updated_definition=None,
        )
