
from typing import List
from uuid import UUID
import json
import structlog
from backend.config.llm import get_chat_model
from backend.models.schemas import PropositionCreate, Chunk
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger()

class PropositionExtractionAgent:
    """
    Agent 2: Proposition Extraction Agent.
    Decomposes chunks into atomic propositions.
    """
    
    def __init__(self, model: str = None):
        self.llm = get_chat_model(model=model, json_mode=True)
        
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def extract_propositions(self, chunk: Chunk) -> List[PropositionCreate]:
        """
        Extract propositions from a chunk.
        """
        logger.info("extract_propositions: Starting", chunk_id=str(chunk.id))
        
        prompt = f"""
        You are an expert at extracting atomic propositions from text.
        Decompose the following text into a list of atomic, self-contained declarative statements (propositions).
        Each proposition must be understandable on its own without resolving pronouns like "it" or "he".
        
        Input Text:
        "{chunk.content}"
        
        Output JSON:
        {{
            "propositions": [
                {{
                    "content": "Atomic fact 1",
                    "confidence": 0.95
                }},
                ...
            ]
        }}
        """
        
        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content.replace("```json", "").replace("```", "").strip()
            data = json.loads(content)
            
            output = []
            for item in data.get("propositions", []):
                output.append(PropositionCreate(
                    note_id=chunk.note_id,
                    chunk_id=chunk.id,
                    content=item["content"],
                    confidence=item.get("confidence", 0.0),
                    is_atomic=True
                ))
                
            return output
            
        except Exception as e:
            logger.error("extract_propositions: Failed", error=str(e))
            return []
