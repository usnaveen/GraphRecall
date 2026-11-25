"""Map-the-territory cards (backend/services/territory.py). No LLM.

GET  /api/territory/cards?limit=      concepts with >= 3 subtopics, as card payloads
GET  /api/territory/{concept_id}      one card
POST /api/territory/{concept_id}/answer  {answer}  -> matched / missed / extras / score / suggested grade
"""
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.auth.middleware import get_current_user
from backend.db.neo4j_client import get_neo4j_client
from backend.services import territory as tt

logger = structlog.get_logger()
router = APIRouter(prefix="/api/territory", tags=["Territory"])


class TerritoryAnswer(BaseModel):
    answer: str = Field(default="", max_length=4000)


def _card(t: dict) -> dict:
    return {"concept_id": t["id"], "concept_name": t["name"], "domain": t.get("domain"), **tt.card_content(t)}


@router.get("/cards")
async def territory_cards(limit: int = Query(default=5, ge=1, le=20), current_user: dict = Depends(get_current_user)):
    neo = await get_neo4j_client()
    return {"cards": [_card(t) for t in await tt.territories(neo, str(current_user["id"]), limit=limit)]}


@router.get("/{concept_id}")
async def territory_card(concept_id: str, current_user: dict = Depends(get_current_user)):
    neo = await get_neo4j_client()
    t = await tt.territory(neo, str(current_user["id"]), concept_id)
    if not t:
        raise HTTPException(status_code=404, detail="Concept not found")
    return _card(t)


@router.post("/{concept_id}/answer")
async def answer_territory(concept_id: str, body: TerritoryAnswer, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["id"])
    neo = await get_neo4j_client()
    t = await tt.territory(neo, user_id, concept_id)
    if not t:
        raise HTTPException(status_code=404, detail="Concept not found")
    children = [c for c in t.get("children") or [] if c.get("name")]
    if len(children) < tt.MIN_CHILDREN:
        raise HTTPException(status_code=422, detail="This concept has too few subtopics for a territory card")
    g = tt.grade(children, body.answer)
    try:
        from backend.services.knowledge_map import record_territory_evidence

        await record_territory_evidence(user_id, concept_id, g)
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001 - grading must not fail on evidence logging
        logger.warning("territory: evidence not recorded", error=str(e))
    return {"concept_id": concept_id, "concept_name": t["name"], "matched": g.matched, "missed": g.missed,
            "extras": g.extras, "score": g.score, "suggested_difficulty": g.suggested, "total": len(children)}
