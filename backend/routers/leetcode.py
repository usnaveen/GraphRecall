"""LeetCode recall: log problems and attempts; cards and scheduling follow (backend/services/leetcode.py).

GET  /api/leetcode/lookup/{number}          fetch + cache public LeetCode problem metadata
POST /api/leetcode/problems                 create or update by title
GET  /api/leetcode/problems                 list, with attempt counts and last outcome
GET  /api/leetcode/problems/{id}            one problem + attempts + its card ids
POST /api/leetcode/problems/{id}/attempts   log solved/hint/failed (+ mistake); failed -> due now
GET  /api/leetcode/weak-spots               mistakes grouped by tag and pattern
"""
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth.middleware import get_current_user
from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.services import leetcode as lc

logger = structlog.get_logger()
router = APIRouter(prefix="/api/leetcode", tags=["LeetCode"])

_PCOLS = ("id::text AS id, number, title, url, difficulty, pattern, tags, key_insight, pseudocode, "
          "solution, language, complexity, concept_id, pattern_concept_id, created_at, updated_at")


class ProblemIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    number: Optional[int] = Field(default=None, ge=1, le=50000)
    url: Optional[str] = Field(default=None, max_length=500)
    difficulty: Optional[Literal["easy", "medium", "hard"]] = None
    pattern: Optional[str] = Field(default=None, max_length=80)
    tags: Optional[list[str]] = Field(default=None, max_length=30)
    key_insight: Optional[str] = Field(default=None, max_length=1000)
    pseudocode: Optional[str] = Field(default=None, max_length=4000)
    solution: Optional[str] = Field(default=None, max_length=20000)
    language: Optional[str] = Field(default=None, max_length=30)
    complexity: Optional[str] = Field(default=None, max_length=80)


class AttemptIn(BaseModel):
    outcome: Literal["solved", "hint", "failed"]
    mistake: Optional[str] = Field(default=None, max_length=1000)
    mistake_tag: Optional[Literal[tuple(lc.MISTAKE_TAGS)]] = None  # type: ignore[valid-type]
    minutes: Optional[int] = Field(default=None, ge=0, le=600)


def _ser(r: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}


async def _attempts(pg, user_id: str, problem_id: str) -> list[dict]:
    return await pg.execute_query(
        "SELECT id::text AS id, outcome, mistake, mistake_tag, minutes, created_at FROM coding_attempts "
        "WHERE user_id = CAST(:u AS uuid) AND problem_id = CAST(:p AS uuid) ORDER BY created_at",
        {"u": user_id, "p": problem_id},
    ) or []


async def _get(pg, user_id: str, problem_id: str) -> dict:
    rows = await pg.execute_query(
        f"SELECT {_PCOLS} FROM coding_problems WHERE id::text = :p AND user_id = CAST(:u AS uuid)",
        {"p": problem_id, "u": user_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Problem not found")
    return rows[0]


@router.get("/lookup/{number}")
async def lookup_by_number(number: int, current_user: dict = Depends(get_current_user)):
    if number < 1:
        raise HTTPException(status_code=404, detail=f"No LeetCode problem #{number}")
    pg = await get_postgres_client()
    try:
        item = await lc.lookup_problem(pg, number)
    except lc.LeetCodeUpstreamError as exc:
        logger.warning("leetcode lookup upstream error", number=number, error=str(exc))
        raise HTTPException(status_code=502, detail="LeetCode lookup service unavailable")
    if item is None:
        raise HTTPException(status_code=404, detail=f"No LeetCode problem #{number}")
    return item


@router.post("/problems")
async def upsert_problem(body: ProblemIn, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["id"])
    if body.url and not body.url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must be http(s)")
    pg = await get_postgres_client()
    data = body.model_dump()
    clean_tags = [t.strip() for t in (data.get("tags") or []) if t and t.strip()]
    data["tags"] = clean_tags
    if not data.get("pattern") and clean_tags:
        data["pattern"] = lc.suggest_pattern(clean_tags)
    rows = await pg.execute_query(
        f"""
        INSERT INTO coding_problems (user_id, number, title, url, difficulty, pattern, tags, key_insight, pseudocode,
                                     solution, language, complexity)
        VALUES (CAST(:u AS uuid), :number, :title, :url, :difficulty, :pattern, :tags, :key_insight, :pseudocode,
                :solution, :language, :complexity)
        ON CONFLICT (user_id, lower(title)) DO UPDATE SET
            number = COALESCE(EXCLUDED.number, coding_problems.number),
            url = COALESCE(EXCLUDED.url, coding_problems.url),
            difficulty = COALESCE(EXCLUDED.difficulty, coding_problems.difficulty),
            pattern = COALESCE(EXCLUDED.pattern, coding_problems.pattern),
            tags = CASE WHEN cardinality(EXCLUDED.tags) > 0 THEN EXCLUDED.tags ELSE coding_problems.tags END,
            key_insight = COALESCE(EXCLUDED.key_insight, coding_problems.key_insight),
            pseudocode = COALESCE(EXCLUDED.pseudocode, coding_problems.pseudocode),
            solution = COALESCE(EXCLUDED.solution, coding_problems.solution),
            language = COALESCE(EXCLUDED.language, coding_problems.language),
            complexity = COALESCE(EXCLUDED.complexity, coding_problems.complexity),
            updated_at = now()
        RETURNING {_PCOLS}
        """,
        {"u": user_id, **data},
    )
    problem = rows[0]
    neo = await get_neo4j_client()
    concept_id, pattern_id = await lc.upsert_graph(neo, user_id, problem)
    await pg.execute_update(
        "UPDATE coding_problems SET concept_id = :c, pattern_concept_id = :pc "
        "WHERE id = CAST(:p AS uuid) AND user_id = CAST(:u AS uuid)",
        {"c": concept_id, "pc": pattern_id, "p": problem["id"], "u": user_id},
    )
    problem.update(concept_id=concept_id, pattern_concept_id=pattern_id)
    # Only the problem is scheduled. The pattern concept stays unscheduled unless the user studies it
    # from notes: scheduling it with no cards would make the feed worker spend LLM quota on it.
    await lc.ensure_scheduled(pg, user_id, [concept_id])
    card_ids = await lc.rebuild_cards(pg, user_id, problem, await _attempts(pg, user_id, problem["id"]))
    return {**_ser(problem), "card_ids": card_ids}


@router.get("/problems")
async def list_problems(current_user: dict = Depends(get_current_user)):
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        """
        SELECT p.id::text AS id, p.number, p.title, p.difficulty, p.pattern, p.tags, p.url, p.updated_at,
               count(a.id) AS attempts,
               count(a.id) FILTER (WHERE a.outcome = 'failed') AS failed,
               (array_agg(a.outcome ORDER BY a.created_at DESC))[1] AS last_outcome
        FROM coding_problems p LEFT JOIN coding_attempts a ON a.problem_id = p.id
        WHERE p.user_id = CAST(:u AS uuid)
        GROUP BY p.id ORDER BY p.updated_at DESC LIMIT 500
        """,
        {"u": str(current_user["id"])},
    )
    return {"problems": [_ser(r) for r in rows or []]}


@router.get("/problems/{problem_id}")
async def get_problem(problem_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["id"])
    pg = await get_postgres_client()
    problem = await _get(pg, user_id, problem_id)
    cards = await pg.execute_query(
        "SELECT id::text AS id, front_content AS front, back_content AS back FROM flashcards "
        "WHERE user_id = CAST(:u AS uuid) AND concept_id = :c AND source = 'leetcode'",
        {"u": user_id, "c": problem.get("concept_id")},
    )
    return {**_ser(problem), "attempts": [_ser(a) for a in await _attempts(pg, user_id, problem_id)],
            "cards": cards or []}


@router.post("/problems/{problem_id}/attempts")
async def log_attempt(problem_id: str, body: AttemptIn, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["id"])
    pg = await get_postgres_client()
    problem = await _get(pg, user_id, problem_id)
    await pg.execute_update(
        "INSERT INTO coding_attempts (user_id, problem_id, outcome, mistake, mistake_tag, minutes) "
        "VALUES (CAST(:u AS uuid), CAST(:p AS uuid), :outcome, :mistake, :tag, :minutes)",
        {"u": user_id, "p": problem_id, "outcome": body.outcome, "mistake": (body.mistake or "").strip() or None,
         "tag": body.mistake_tag, "minutes": body.minutes},
    )
    card_ids = await lc.rebuild_cards(pg, user_id, problem, await _attempts(pg, user_id, problem_id))
    try:
        from backend.services.knowledge_map import record_leetcode_evidence

        await record_leetcode_evidence(pg, user_id, concept_id=problem.get("concept_id"),
                                       pattern_concept_id=problem.get("pattern_concept_id"), outcome=body.outcome)
    except Exception as e:  # noqa: BLE001 - logging evidence must not fail the attempt
        logger.warning("leetcode: evidence not recorded", error=str(e))
    if body.outcome == "failed" and problem.get("concept_id"):
        await lc.make_due_now(pg, user_id, problem["concept_id"])
    return {"problem_id": problem_id, "card_ids": card_ids, "due_now": body.outcome == "failed"}


@router.get("/weak-spots")
async def weak_spots(current_user: dict = Depends(get_current_user)):
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        """
        SELECT coalesce(a.mistake_tag, 'untagged') AS tag, coalesce(p.pattern, 'no pattern') AS pattern,
               count(*) AS n, max(a.created_at) AS last_seen
        FROM coding_attempts a JOIN coding_problems p ON p.id = a.problem_id
        WHERE a.user_id = CAST(:u AS uuid) AND a.outcome <> 'solved'
        GROUP BY 1, 2 ORDER BY n DESC, last_seen DESC LIMIT 20
        """,
        {"u": str(current_user["id"])},
    )
    return {"weak_spots": [{**_ser(r), "label": lc.MISTAKE_TAGS.get(r["tag"], r["tag"])} for r in rows or []]}
