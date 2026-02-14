"""Agent for generating study content: MCQs, flashcards, fill-in-blank, mermaid diagrams."""

import json
from pathlib import Path
from typing import Optional

import structlog
from backend.config.llm import get_chat_model
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.models.feed_schemas import (
    MCQQuestion,
    MCQOption,
    FillBlankQuestion,
    TermCard,
    MermaidDiagram,
    CodeChallengeQuestion,
)
from backend.agents.mermaid_agent import MermaidAgent


def _normalize_difficulty(value: object, fallback: int = 5) -> int:
    """Coerce difficulty to int 1-10 from common LLM outputs."""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return max(1, min(10, value))
    if isinstance(value, float):
        return max(1, min(10, int(round(value))))
    if isinstance(value, str):
        text = value.strip().lower()
        mapping = {
            "easy": 3,
            "medium": 5,
            "med": 5,
            "moderate": 5,
            "hard": 8,
            "difficult": 8,
            "very hard": 9,
            "advanced": 8,
        }
        if text in mapping:
            return mapping[text]
        import re
        match = re.search(r"(\d{1,2})", text)
        if match:
            try:
                return max(1, min(10, int(match.group(1))))
            except ValueError:
                return fallback
    return fallback

logger = structlog.get_logger()

# Load prompts
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _parse_llm_json(response) -> dict:
    """Safely parse JSON from LLM response, handling empty/malformed content."""
    content = getattr(response, "content", None)
    if not content or not content.strip():
        raise ValueError("LLM returned empty response")

    text = content.strip()
    # Strip markdown code fences if present
    if text.startswith("```json"):
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif text.startswith("```"):
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    # Additional cleaning for common LLM JSON errors
    import re
    # Remove control characters that often break json.loads
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)

    return json.loads(text)


class ContentGeneratorAgent:
    """
    Agent for generating various types of study content.
    
    Uses Gemini for cost-effective, high-quality content generation.
    """
    
    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.7,  # Slightly creative for varied questions
    ):
        self.model_name = model
        self.llm = get_chat_model(
            model=model,
            temperature=temperature,
            json_mode=True,
        )
        self.mermaid_agent = MermaidAgent()
    
    # =========================================================================
    # MCQ Generation
    # =========================================================================
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    async def generate_mcq(
        self,
        concept_name: str,
        concept_definition: str,
        related_concepts: list[str],
        difficulty: int = 5,
        num_options: int = 4,
        propositions: list[str] = [],
    ) -> MCQQuestion:
        """
        Generate a multiple choice question for a concept.
        
        Args:
            concept_name: Name of the concept
            concept_definition: Definition of the concept
            related_concepts: Related concepts for context/distractors
            difficulty: Difficulty level 1-10
            num_options: Number of answer options (default 4)
            
        Returns:
            MCQQuestion object
        """
        normalized_difficulty = _normalize_difficulty(difficulty, fallback=5)
        prompt = f"""Generate a multiple choice question to test understanding of this concept.

CONCEPT: {concept_name}
DEFINITION: {concept_definition}
RELATED CONCEPTS: {', '.join(related_concepts[:5])}
DIFFICULTY LEVEL: {normalized_difficulty}/10 (1=very easy, 10=very hard)

Requirements:
1. Create a clear, unambiguous question
2. Provide exactly {num_options} options (A, B, C, D)
3. Only ONE option should be correct
4. Distractors should be plausible but clearly wrong if you understand the concept
5. For higher difficulty: use application/analysis questions instead of recall
6. Include a brief explanation of why the correct answer is right
7. Use the SUPPORTING FACTS (if provided) to ensure accuracy

SUPPORTING FACTS:
{'- ' + chr(10).join(propositions[:5]) if propositions else 'None provided (General knowledge)'}

Output JSON format:
{{
    "question": "The question text",
    "options": [
        {{"id": "A", "text": "Option A text", "is_correct": false}},
        {{"id": "B", "text": "Option B text", "is_correct": true}},
        {{"id": "C", "text": "Option C text", "is_correct": false}},
        {{"id": "D", "text": "Option D text", "is_correct": false}}
    ],
    "explanation": "Explanation of the correct answer",
    "difficulty": {normalized_difficulty}
}}"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            parsed = _parse_llm_json(response)

            options = [
                MCQOption(
                    id=opt["id"],
                    text=opt["text"],
                    is_correct=opt["is_correct"],
                )
                for opt in parsed["options"]
            ]

            return MCQQuestion(
                concept_id="",  # To be set by caller
                question=parsed["question"],
                options=options,
                explanation=parsed.get("explanation", ""),
                difficulty=_normalize_difficulty(parsed.get("difficulty"), normalized_difficulty),
            )

        except Exception as e:
            logger.error("ContentGenerator: MCQ generation failed", error=str(e))
            raise
    
    async def generate_mcq_batch(
        self,
        concepts: list[dict],
        num_per_concept: int = 2,
    ) -> list[MCQQuestion]:
        """
        Generate multiple MCQs for a batch of concepts using parallel LLM calls.

        Args:
            concepts: List of concept dictionaries with name, definition, etc.
            num_per_concept: Number of MCQs to generate per concept

        Returns:
            List of validated MCQQuestion objects
        """
        import asyncio

        async def _generate_one(concept: dict) -> list[MCQQuestion]:
            results = []
            for _ in range(num_per_concept):
                try:
                    mcq = await self.generate_mcq(
                        concept_name=concept["name"],
                        concept_definition=concept["definition"],
                        related_concepts=concept.get("related_concepts", []),
                        difficulty=int(concept.get("complexity_score", 5)),
                        propositions=concept.get("propositions", []),
                    )
                    mcq.concept_id = concept.get("id", "")

                    # VALIDATION: Ensure exactly one correct answer in options
                    correct_options = [o for o in mcq.options if o.is_correct]
                    if not correct_options:
                        logger.warning(
                            "MCQ validation: No correct answer, forcing first option",
                            concept=concept["name"],
                        )
                        if mcq.options:
                            mcq.options[0].is_correct = True
                    elif len(correct_options) > 1:
                        logger.warning(
                            "MCQ validation: Multiple correct answers, keeping first",
                            concept=concept["name"],
                        )
                        for opt in mcq.options:
                            opt.is_correct = False
                        correct_options[0].is_correct = True

                    results.append(mcq)
                except Exception as e:
                    logger.warning(
                        "ContentGenerator: Failed to generate MCQ for concept",
                        concept=concept["name"],
                        error=str(e),
                    )
            return results

        # Run all concept MCQ generations in parallel
        tasks = [_generate_one(concept) for concept in concepts]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_mcqs = []
        for result in batch_results:
            if isinstance(result, list):
                all_mcqs.extend(result)
            elif isinstance(result, Exception):
                logger.warning("MCQ batch: task failed", error=str(result))

        return all_mcqs
    
    # =========================================================================
    # Fill-in-the-Blank Generation
    # =========================================================================
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    async def generate_fill_blank(
        self,
        concept_name: str,
        concept_definition: str,
        difficulty: int = 5,
    ) -> FillBlankQuestion:
        """
        Generate a fill-in-the-blank question for a concept.
        
        Args:
            concept_name: Name of the concept
            concept_definition: Definition of the concept
            difficulty: Difficulty level 1-10
            
        Returns:
            FillBlankQuestion object
        """
        normalized_difficulty = _normalize_difficulty(difficulty, fallback=5)
        prompt = f"""Generate a fill-in-the-blank sentence to test understanding of this concept.

CONCEPT: {concept_name}
DEFINITION: {concept_definition}
DIFFICULTY LEVEL: {normalized_difficulty}/10

Requirements:
1. Create a meaningful sentence where the blank tests key understanding
2. Use _____ (5 underscores) to mark the blank
3. The answer should be a single word or short phrase
4. For higher difficulty: test application, not just definition recall
5. Provide a helpful hint that doesn't give away the answer

Output JSON format:
{{
    "sentence": "The sentence with _____ for the blank",
    "answers": ["correct answer", "alternative acceptable answer"],
    "hint": "A helpful hint",
    "difficulty": {normalized_difficulty}
}}"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            parsed = _parse_llm_json(response)

            return FillBlankQuestion(
                concept_id="",  # To be set by caller
                sentence=parsed["sentence"],
                answers=parsed["answers"],
                hint=parsed.get("hint"),
                difficulty=_normalize_difficulty(parsed.get("difficulty"), normalized_difficulty),
            )

        except Exception as e:
            logger.error("ContentGenerator: Fill-blank generation failed", error=str(e))
            raise
    
    # =========================================================================
    # Flashcard Generation
    # =========================================================================
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    async def generate_flashcards(
        self,
        concept_name: str,
        concept_definition: str,
        related_concepts: list[str],
        num_cards: int = 3,
    ) -> list[dict]:
        """
        Generate flashcards for a concept.
        
        Creates different types of cards:
        - Basic: term → definition
        - Reverse: definition → term
        - Application: scenario → concept
        
        Args:
            concept_name: Name of the concept
            concept_definition: Definition of the concept
            related_concepts: Related concepts for context
            num_cards: Number of cards to generate
            
        Returns:
            List of flashcard dictionaries
        """
        prompt = f"""Generate {num_cards} flashcards to help learn this concept.

CONCEPT: {concept_name}
DEFINITION: {concept_definition}
RELATED CONCEPTS: {', '.join(related_concepts[:5])}

Create varied card types:
1. Basic (term → definition)
2. Reverse (definition hint → term)
3. Application (real-world example → concept)
4. Comparison (how it differs from related concept)

Output JSON format:
{{
    "flashcards": [
        {{
            "front": "Front of card (question/prompt)",
            "back": "Back of card (answer)",
            "card_type": "basic|reverse|application|comparison"
        }}
    ]
}}"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            parsed = _parse_llm_json(response)

            return parsed.get("flashcards", [])

        except Exception as e:
            logger.error("ContentGenerator: Flashcard generation failed", error=str(e))
            raise

    async def generate_cloze_from_propositions(
        self,
        propositions: list[dict], # [{content, confidence, ...}]
        count: int = 5
    ) -> list[dict]:
        """
        Generate high-quality Cloze Deletion flashcards from atomic propositions.
        """
        # Filter for high confidence propositions
        valid_props = [p["content"] for p in propositions if p.get("confidence", 0) > 0.7]
        if not valid_props:
            return []
            
        selected_props = valid_props[:10] # Limit context size
        
        prompt = f"""Generate {count} Cloze Deletion flashcards based STRICTLY on these facts.

FACTS:
{'- ' + chr(10).join(selected_props)}

Instructions:
1. Select the most important facts.
2. Create a sentence where the KEYWORD is replaced by [___].
3. The context must be sufficient to answer the question.
4. DO NOT hallucinate info not in the facts.

Output JSON format:
{{
    "flashcards": [
        {{
            "front": "Sentence with [___]...",
            "back": "Answer",
            "concept": "Derived from fact"
        }}
    ]
}}"""
        try:
            response = await self.llm.ainvoke(prompt)
            parsed = _parse_llm_json(response)
            return parsed.get("flashcards", [])
        except Exception as e:
            logger.error("ContentGenerator: Cloze generation failed", error=str(e))
            return []
    
    # =========================================================================
    # Mermaid Diagram Generation
    # =========================================================================
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    async def generate_mermaid_diagram(
        self,
        concepts: list[dict],
        diagram_type: str = "flowchart",
        title: Optional[str] = None,
    ) -> MermaidDiagram:
        """
        Generate a mermaid diagram showing relationships between concepts.
        
        Delegates to specialized MermaidAgent for 'sniper precision'.
        """
        try:
            # Delegate to specialized agent
            if diagram_type == "mindmap":
                # Use the first concept as root if not specified
                root_concept = concepts[0]["name"] if concepts else "System"
                result = await self.mermaid_agent.generate_mindmap(root_concept, concepts[1:])
                chart_type = "mindmap"
            else:
                # Flowchart default
                steps = [f"Understand {c['name']}: {c['definition'][:50]}" for c in concepts]
                result = await self.mermaid_agent.generate_flowchart(title or "Concept Flow", steps)
                chart_type = "flowchart"
            
            return MermaidDiagram(
                diagram_type=chart_type,
                mermaid_code=result.code,
                title=title or result.explanation[:50],
                source_concepts=[c.get("id", "") for c in concepts],
            )
            
        except Exception as e:
            logger.error("ContentGenerator: Mermaid generation failed", error=str(e))
            raise
    
    # =========================================================================
    # Mixed Batch Generation
    # =========================================================================

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    async def generate_mixed_batch(
        self,
        topic: str,
        definition: str,
        related_concepts: list[str] = [],
        count: int = 10,
    ) -> list[dict]:
        """
        Generate a diverse mix of study content in a single LLM call.
        Includes: MCQ, Term Cards, Fill-blanks, Code Challenges, and Showcases.
        """
        prompt = f"""Generate {count} diverse study items for the topic: {topic}.
        
DEFINITION: {definition}
RELATED: {', '.join(related_concepts[:5])}

Requirements:
1. Create a HEALTHY MIX of the following 5 types:
   - 'mcq': Multiple choice question.
   - 'term_card': Term on front, detailed definition/explanation on back.
   - 'fill_blank': Sentence with _____ for a key word.
   - 'code_challenge': SQL query, NumPy/Pandas line, CLI command, or Docker instruction.
   - 'concept_showcase': Engaging visual metaphor, tagline, and emoji.

2. Structure each item in a way that matches its type requirements.

Output JSON format:
{{
    "items": [
        {{
            "type": "mcq",
            "content": {{ "question": "...", "options": [{{ "id": "A", "text": "...", "is_correct": true }}, ...], "explanation": "..." }}
        }},
        {{
            "type": "term_card",
            "content": {{ "front": "The Term", "back": "Detailed explanation..." }}
        }},
        {{
            "type": "fill_blank",
            "content": {{ "sentence": "...", "answers": ["word"], "hint": "..." }}
        }},
        {{
            "type": "code_challenge",
            "content": {{ 
                "language": "sql|python|bash|docker", 
                "instruction": "...", 
                "initial_code": "optional", 
                "solution_code": "...", 
                "explanation": "..." 
            }}
        }},
        {{
            "type": "concept_showcase",
            "content": {{ 
                "tagline": "...", 
                "visual_metaphor": "...", 
                "key_points": [], 
                "emoji_icon": "..." 
            }}
        }}
    ]
}}
Rules: Exactly {count} items total. Variety is key."""

        try:
            response = await self.llm.ainvoke(prompt)
            data = _parse_llm_json(response)
            return data.get("items", [])
        except Exception as e:
            logger.error("ContentGenerator: Mixed batch generation failed", error=str(e))
            raise

    # =========================================================================
    # Specialized Generation
    # =========================================================================

    async def generate_code_challenge(
        self,
        topic: str,
        definition: str,
        difficulty: int = 5
    ) -> CodeChallengeQuestion:
        """Specifically generate a code-related challenge."""
        normalized_difficulty = _normalize_difficulty(difficulty, fallback=5)
        prompt = f"""Generate a code completion or command-line challenge for: {topic}.
CONTEXT: {definition}
DIFFICULTY: {normalized_difficulty}/10

Respond with JSON:
{{
    "language": "python|sql|bash|docker|css",
    "instruction": "What is the command to...",
    "initial_code": "optional starting point",
    "solution_code": "The correct answer",
    "explanation": "Why this is correct",
    "difficulty": {normalized_difficulty}
}}"""
        try:
            response = await self.llm.ainvoke(prompt)
            parsed = _parse_llm_json(response)
            return CodeChallengeQuestion(
                concept_id="",
                language=parsed["language"],
                instruction=parsed["instruction"],
                initial_code=parsed.get("initial_code"),
                solution_code=parsed["solution_code"],
                explanation=parsed["explanation"],
                difficulty=_normalize_difficulty(parsed.get("difficulty"), normalized_difficulty)
            )
        except Exception as e:
            logger.error("ContentGenerator: Code challenge failed", error=str(e))
            raise
    
    # =========================================================================
    # Concept Showcase Generation
    # =========================================================================
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
    )
    async def generate_concept_showcase(
        self,
        concept_name: str,
        concept_definition: str,
        domain: str,
        complexity_score: float,
        prerequisites: list[str],
        related_concepts: list[str],
    ) -> dict:
        """
        Generate a rich concept showcase card for the feed.
        
        This creates an engaging, Instagram-style presentation of a concept
        with visual metaphor, key points, and connections.
        
        Returns:
            Dictionary with showcase content
        """
        prompt = f"""Create an engaging concept showcase for a learning app.

CONCEPT: {concept_name}
DEFINITION: {concept_definition}
DOMAIN: {domain}
COMPLEXITY: {complexity_score}/10
PREREQUISITES: {', '.join(prerequisites[:5])}
RELATED: {', '.join(related_concepts[:5])}

Create content for a visually appealing "concept card" that:
1. Has a memorable visual metaphor/analogy
2. Highlights 3-4 key points
3. Suggests a real-world application
4. Notes important connections

Output JSON format:
{{
    "tagline": "A catchy one-liner about the concept",
    "visual_metaphor": "A visual/everyday analogy to understand the concept",
    "key_points": ["point 1", "point 2", "point 3"],
    "real_world_example": "A practical application or example",
    "connections_note": "How this connects to prerequisites/related concepts",
    "emoji_icon": "A single emoji that represents this concept"
}}"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            parsed = _parse_llm_json(response)

            return {
                "concept_name": concept_name,
                "definition": concept_definition,
                "domain": domain,
                "complexity_score": complexity_score,
                "prerequisites": prerequisites,
                "related_concepts": related_concepts,
                **parsed,
            }

        except Exception as e:
            logger.error("ContentGenerator: Showcase generation failed", error=str(e))
            # Return basic showcase on failure
            return {
                "concept_name": concept_name,
                "definition": concept_definition,
                "domain": domain,
                "complexity_score": complexity_score,
                "prerequisites": prerequisites,
                "related_concepts": related_concepts,
                "tagline": concept_definition[:50] + "...",
                "visual_metaphor": "",
                "key_points": [],
                "real_world_example": "",
                "connections_note": "",
                "emoji_icon": "📚",
            }
