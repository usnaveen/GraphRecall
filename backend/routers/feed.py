"""Feed Router - Active Recall Feed Endpoints."""

import json
import os
import uuid
import random
import asyncio
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from backend.agent_bridge import bridge_enabled
from backend.auth.middleware import get_current_user
from backend.agent_v2.enqueue import enqueue_durable_job
from backend.agent_v2.protocols import FeedBufferEnsurePayload
from backend.config.llm import get_chat_model

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.models.feed_schemas import (
    DifficultyLevel,
    FeedFilterRequest,
    FeedItem,
    FeedItemType,
    FeedResponse,
    ReviewResult,
    UserStats,
)
from backend.services.feed_service import FeedService
from backend.services.spaced_repetition import SpacedRepetitionService
from backend.services.review_target import UnresolvableReviewTarget, resolve_review_concept
from backend.services import creative_cards
from backend.services import knowledge_map as km
from backend.agents.research_agent import WebResearchAgent

logger = structlog.get_logger()


router = APIRouter(prefix="/api/feed", tags=["Feed"])


def _resolve_user_sr_algorithm(current_user: dict) -> str:
    """Resolve user's spaced repetition algorithm, defaulting to SM-2 until Anki benchmark gate."""
    user_settings = current_user.get("settings_json") or {}
    if isinstance(user_settings, str):
        try:
            user_settings = json.loads(user_settings)
        except Exception:
            user_settings = {}
    return user_settings.get("sr_algorithm") or os.getenv("FEED_DEFAULT_SR_ALGORITHM", "sm2")


@router.get("", response_model=FeedResponse)
async def get_feed(
    current_user: dict = Depends(get_current_user),
    max_items: int = Query(default=20, le=50),
    item_types: Optional[str] = Query(
        default=None,
        description="Comma-separated item types: flashcard,mcq,fill_blank,showcase",
    ),
    domains: Optional[str] = Query(
        default=None,
        description="Comma-separated domains to filter",
    ),
):
    """
    Get the user's active recall feed.
    
    Returns a personalized mix of:
    - Due items based on spaced repetition
    - MCQs, flashcards, fill-in-blank questions
    - Concept showcases
    - User uploads (screenshots, infographics)
    
    Items are sorted by priority (overdue items first).
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()

        algorithm = _resolve_user_sr_algorithm(current_user)
        feed_service = FeedService(pg_client, neo4j_client, sr_algorithm=algorithm)
        
        # Parse item types
        parsed_types = None
        if item_types:
            try:
                parsed_types = [FeedItemType(t.strip()) for t in item_types.split(",")]
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid item type: {e}")
        
        # Parse domains
        parsed_domains = None
        if domains:
            parsed_domains = [d.strip() for d in domains.split(",")]
        
        request = FeedFilterRequest(
            user_id=str(current_user["id"]),
            max_items=max_items,
            item_types=parsed_types,
            domains=parsed_domains,
        )
        
        response = await feed_service.get_feed(request)

        # Agent bridge: prepend approved, agent-curated items (off unless enabled).
        if bridge_enabled() and (
            parsed_types is None or FeedItemType.AGENT_CURATED in parsed_types
        ):
            try:
                from backend.agent_bridge.feed_integration import (
                    agent_feed_items,
                    filter_by_domains,
                    merge_into_feed,
                )
                from backend.agent_bridge.repository import PostgresBridgeRepository

                curated = await agent_feed_items(
                    PostgresBridgeRepository(pg_client), request.user_id, limit=5
                )
                curated = await filter_by_domains(
                    neo4j_client, request.user_id, curated, parsed_domains
                )
                response.items = merge_into_feed(curated, response.items, max_items)
            except Exception as e:  # never break the core feed
                logger.warning("Feed: agent-curated items skipped", error=str(e))
        
        await _add_territory_card(response, request, neo4j_client)
        await _add_sandbox_card(response, request, pg_client)
        await _add_creative_card(response, request, pg_client)

        # Inject Daily Goal & Trigger Durable Pre-gen Buffer
        response.daily_goal = await feed_service.get_daily_goal(request.user_id)
        await enqueue_durable_job(
            request.user_id,
            "feed.buffer_ensure",
            FeedBufferEnsurePayload(trigger="feed_get").model_dump(),
            dedupe_window_seconds=3600,
            pg_client=pg_client,
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Feed: Error getting feed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def _add_territory_card(response, request, neo4j_client) -> None:
    """One map-the-territory card per feed load, preferring a parent of a concept already in the feed.
    No LLM: the card is built from SUBTOPIC_OF edges. Best effort; the feed never fails on it."""
    if request.item_types and FeedItemType.TERRITORY not in request.item_types:
        return
    try:
        from backend.services import territory as tt

        options = await tt.territories(neo4j_client, request.user_id, limit=12)
        if request.domains:
            options = [t for t in options if t.get("domain") in request.domains]
        if not options:
            return
        in_feed = {i.concept_id for i in response.items if i.concept_id}
        option = next((t for t in options if t["id"] in in_feed), None)
        if option is None:
            import random

            option = random.choice(options)
        card = FeedItem(
            id=f"territory:{option['id']}",
            item_type=FeedItemType.TERRITORY,
            content=tt.card_content(option),
            concept_id=option["id"],
            concept_name=option["name"],
            domain=option.get("domain"),
            priority_score=0.75,
        )
        response.items.insert(min(2, len(response.items)), card)
        if len(response.items) > request.max_items:
            response.items.pop()
    except Exception as e:  # noqa: BLE001
        logger.warning("Feed: territory card skipped", error=str(e))


async def _add_sandbox_card(response, request, pg_client) -> None:
    """One code-sandbox card per feed load, matched to concepts in this feed and LeetCode weak spots.
    The code runs on the phone; the server only ships the challenge and records the result."""
    if request.item_types and FeedItemType.CODE_SANDBOX not in request.item_types:
        return
    try:
        from backend.services.code_sandbox_cards import build_sandbox_feed_payload, select_sandbox_challenge

        names = [i.concept_name for i in response.items if i.concept_name]
        weak = await pg_client.execute_query(
            "SELECT DISTINCT p.pattern FROM coding_attempts a JOIN coding_problems p ON p.id = a.problem_id "
            "WHERE a.user_id = CAST(:u AS uuid) AND a.outcome <> 'solved' AND p.pattern IS NOT NULL LIMIT 5",
            {"u": request.user_id})
        challenge = select_sandbox_challenge(names, [r["pattern"] for r in weak or []])
        if request.domains:
            payload_domain = build_sandbox_feed_payload(challenge)["domain"]
            if payload_domain not in request.domains:
                return
        p = build_sandbox_feed_payload(challenge)
        card = FeedItem(id=p["id"], item_type=FeedItemType.CODE_SANDBOX, content=p["content"],
                        concept_id=None, concept_name=p["concept_name"], domain=p["domain"],
                        priority_score=p["priority_score"])
        response.items.insert(min(4, len(response.items)), card)
        if len(response.items) > request.max_items:
            response.items.pop()
    except Exception as e:  # noqa: BLE001
        logger.warning("Feed: sandbox card skipped", error=str(e))


def _resolve_creative_card_domain(
    card,
    feed_items: list[FeedItem],
    requested_domains: Optional[list[str]],
) -> Optional[str]:
    """Resolve domain for a creative card from matched feed items or tags, honoring domain filters."""
    extra = getattr(card, "scenario", "")
    matched_domains: list[tuple[int, str]] = []
    for item in feed_items:
        if not item.concept_name or not item.domain:
            continue
        score = creative_cards._match_score(
            [item.concept_name],
            title=card.title,
            concept_name=card.concept_name,
            tags=card.tags,
            extra=extra,
        )
        if score > 0:
            matched_domains.append((score, item.domain))
    matched_domains.sort(key=lambda pair: -pair[0])

    tag_set = {t.lower() for t in card.tags}
    if "leetcode" in tag_set or "algorithms" in tag_set:
        inferred = "Coding Interviews"
    elif ("sql" in tag_set or "postgres" in tag_set) and "rag" not in tag_set and "ml" not in tag_set:
        inferred = "Database Systems"
    else:
        inferred = "AI & ML"

    if not requested_domains:
        return matched_domains[0][1] if matched_domains else inferred

    allowed = {d.strip() for d in requested_domains if d and d.strip()}
    for _, dom in matched_domains:
        if dom in allowed:
            return dom
    if inferred in allowed:
        return inferred

    alias_domains: set[str] = set()
    if tag_set & {"ml", "deep-learning", "llm", "rag", "embeddings", "attention", "prompt-caching"}:
        alias_domains.update({"AI & ML", "Machine Learning", "RAG", "Deep Learning", "LLMs"})
    if tag_set & {"sql", "postgres", "pgvector", "multi-tenant"}:
        alias_domains.update({"Database Systems", "Databases"})
    if tag_set & {"systems", "rate-limiting", "redis", "reliability", "security", "sandbox"}:
        alias_domains.update({"Systems", "Distributed Systems", "System Design"})
    if tag_set & {"leetcode", "algorithms", "binary-search"}:
        alias_domains.update({"Coding Interviews", "Algorithms", "Data Structures"})

    for req_dom in requested_domains:
        cleaned = (req_dom or "").strip()
        if cleaned in alias_domains:
            return cleaned
    return None


# A creative card the user answered in this window is not shown again.
_CREATIVE_REPEAT_DAYS = 30
# _match_score gives 10 for an exact concept/tag match, 6 for a name inside the card text and 2 per
# shared word. One shared word ("algorithm", "attention") is not relevance: a geometry feed pulled
# in a code-sandboxing duel that way. No card beats an unrelated card.
_MIN_CREATIVE_RELEVANCE = 4


async def _recently_answered_creative_ids(pg_client, user_id: str) -> list[str]:
    """Card ids with spot_the_bug / tradeoff_duel evidence in the last _CREATIVE_REPEAT_DAYS days."""
    try:
        rows = await pg_client.execute_query(
            "SELECT DISTINCT source_id FROM knowledge_evidence "
            "WHERE user_id = CAST(:u AS uuid) AND created_at > now() - make_interval(days => :d) "
            "AND (source_id LIKE 'spot_the_bug:%' OR source_id LIKE 'tradeoff_duel:%')",
            {"u": user_id, "d": _CREATIVE_REPEAT_DAYS},
        )
        return [str(r["source_id"]).split(":", 1)[1] for r in rows if r.get("source_id")]
    except Exception as e:  # noqa: BLE001 - repeats are a nuisance, not a failure
        logger.warning("Feed: answered creative cards unavailable", error=str(e))
        return []


async def _add_creative_card(response, request, pg_client=None) -> None:
    """One creative card (spot_the_bug or tradeoff_duel) per feed load, matched to feed concepts.
    Only a card that matches something in this feed (score > 0) and that the user has not answered
    in the last 30 days. Zero LLM cost; respects item_types, domains and max_items; never fails the feed."""
    if request.max_items <= 0:
        return
    allow_spot = request.item_types is None or FeedItemType.SPOT_THE_BUG in request.item_types
    allow_duel = request.item_types is None or FeedItemType.TRADEOFF_DUEL in request.item_types
    if not allow_spot and not allow_duel:
        return
    try:
        names = [i.concept_name for i in response.items if i.concept_name]
        if not names:
            return
        answered = await _recently_answered_creative_ids(pg_client, request.user_id) if pg_client else []

        def _pick_valid_spot():
            if not allow_spot:
                return None, None, -1
            excluded: list[str] = list(answered)
            while True:
                cand = creative_cards.select_spot_the_bug(names, exclude_ids=excluded)
                if cand is None:
                    return None, None, -1
                sc = creative_cards._match_score(
                    names, title=cand.title, concept_name=cand.concept_name, tags=cand.tags
                )
                if sc < _MIN_CREATIVE_RELEVANCE:
                    return None, None, -1  # the best remaining card matches nothing in this feed
                dom = _resolve_creative_card_domain(cand, response.items, request.domains)
                if dom is not None:
                    return cand, dom, sc
                excluded.append(cand.id)

        def _pick_valid_duel():
            if not allow_duel:
                return None, None, -1
            excluded: list[str] = list(answered)
            while True:
                cand = creative_cards.select_tradeoff_duel(names, exclude_ids=excluded)
                if cand is None:
                    return None, None, -1
                sc = creative_cards._match_score(
                    names,
                    title=cand.title,
                    concept_name=cand.concept_name,
                    tags=cand.tags,
                    extra=cand.scenario,
                )
                if sc < _MIN_CREATIVE_RELEVANCE:
                    return None, None, -1
                dom = _resolve_creative_card_domain(cand, response.items, request.domains)
                if dom is not None:
                    return cand, dom, sc
                excluded.append(cand.id)

        spot, spot_dom, spot_score = _pick_valid_spot()
        duel, duel_dom, duel_score = _pick_valid_duel()

        chosen = None
        chosen_type: Optional[FeedItemType] = None
        chosen_domain: Optional[str] = None

        if spot is not None and duel is not None:
            has_spot = any(i.item_type == FeedItemType.SPOT_THE_BUG for i in response.items)
            has_duel = any(i.item_type == FeedItemType.TRADEOFF_DUEL for i in response.items)
            if has_spot and not has_duel:
                chosen, chosen_type, chosen_domain = duel, FeedItemType.TRADEOFF_DUEL, duel_dom
            elif has_duel and not has_spot:
                chosen, chosen_type, chosen_domain = spot, FeedItemType.SPOT_THE_BUG, spot_dom
            elif spot_score > duel_score:
                chosen, chosen_type, chosen_domain = spot, FeedItemType.SPOT_THE_BUG, spot_dom
            elif duel_score > spot_score:
                chosen, chosen_type, chosen_domain = duel, FeedItemType.TRADEOFF_DUEL, duel_dom
            elif len(response.items) % 2 == 0:
                chosen, chosen_type, chosen_domain = spot, FeedItemType.SPOT_THE_BUG, spot_dom
            else:
                chosen, chosen_type, chosen_domain = duel, FeedItemType.TRADEOFF_DUEL, duel_dom
        elif spot is not None:
            chosen, chosen_type, chosen_domain = spot, FeedItemType.SPOT_THE_BUG, spot_dom
        elif duel is not None:
            chosen, chosen_type, chosen_domain = duel, FeedItemType.TRADEOFF_DUEL, duel_dom
        else:
            return

        target_key = km.skill_key(chosen.concept_name)
        matched_cid = next(
            (
                i.concept_id
                for i in response.items
                if i.concept_id and i.concept_name and km.skill_key(i.concept_name) == target_key
            ),
            None,
        )
        card = FeedItem(
            id=f"{chosen_type.value}:{chosen.id}",
            item_type=chosen_type,
            content=chosen.as_dict(),
            concept_id=matched_cid,
            concept_name=chosen.concept_name,
            domain=chosen_domain,
            priority_score=0.8,
        )
        insert_at = min(6, len(response.items), request.max_items - 1)
        response.items.insert(insert_at, card)
        if len(response.items) > request.max_items:
            response.items.pop()
    except Exception as e:  # noqa: BLE001
        logger.warning("Feed: creative card skipped", error=str(e))


class SandboxResultBody(BaseModel):
    challenge_id: str = Field(..., max_length=80)
    concept_name: str = Field(..., max_length=200)
    passed: int = Field(..., ge=0, le=100)
    total: int = Field(..., ge=0, le=100)
    elapsed_ms: int = Field(0, ge=0)


@router.post("/sandbox-result")
async def sandbox_result(body: SandboxResultBody, current_user: dict = Depends(get_current_user)):
    """Record a sandbox run as tested evidence for the concept (all tests 0.9, half 0.45, else 0.15)."""
    from backend.db.neo4j_client import get_neo4j_client as _neo
    from backend.services import knowledge_map as km
    from backend.services.code_sandbox_cards import CodeSandboxSubmission, compute_sandbox_evidence

    user_id = str(current_user["id"])
    ev = compute_sandbox_evidence(CodeSandboxSubmission(
        challenge_id=body.challenge_id, concept_id=None, concept_name=body.concept_name,
        passed_tests=body.passed, total_tests=body.total, elapsed_ms=body.elapsed_ms))
    pg = await get_postgres_client()
    concept = km.match_concept(body.concept_name, await km._user_concepts(await _neo(), user_id))
    await km.add_evidence(pg, user_id, kind="sandbox", signal=ev["score"],
                          concept_id=concept["id"] if concept else None, skill_name=body.concept_name,
                          source_id=f"sandbox:{body.challenge_id}", detail=ev["metadata"])
    return {"recorded": True, "signal": ev["score"], "result": ev["signal_type"],
            "concept_id": concept["id"] if concept else None}


class SpotTheBugGradeRequest(BaseModel):
    card_id: str = Field(..., min_length=1, max_length=120)
    selected_line: int


@router.get("/creative-cards")
async def get_creative_cards(
    current_user: dict = Depends(get_current_user),
    limit: int = Query(default=4, ge=1, le=20),
    exclude_ids: Optional[str] = Query(default=None, description="Comma-separated card IDs to exclude"),
):
    """Select deterministic spot_the_bug and tradeoff_duel cards matched to user's recent/weak concepts (0 LLM)."""
    user_id = str(current_user["id"])
    excluded = [x.strip() for x in (exclude_ids or "").split(",") if x.strip()]

    concept_names: list[str] = []
    seen_names: set[str] = set()

    def _add_name(name: Optional[str]) -> None:
        cleaned = (name or "").strip()
        if cleaned and cleaned.lower() not in seen_names:
            seen_names.add(cleaned.lower())
            concept_names.append(cleaned)

    weak_ids: list[str] = []
    try:
        pg_client = await get_postgres_client()
        weak_rows = await pg_client.execute_query(
            """
            SELECT concept_id
            FROM proficiency_scores
            WHERE user_id = :user_id
            ORDER BY score ASC, next_review_due ASC NULLS LAST
            LIMIT 10
            """,
            {"user_id": user_id},
        )
        weak_ids = [str(r["concept_id"]) for r in (weak_rows or []) if r.get("concept_id")]
    except Exception as exc:  # noqa: BLE001 - best-effort personalization
        logger.warning("Feed: creative-cards weak concept lookup skipped", error=str(exc))

    try:
        neo4j_client = await get_neo4j_client()
        neo_rows = await neo4j_client.execute_query(
            """
            MATCH (c:Concept {user_id: $user_id})
            RETURN c.id AS id, c.name AS name, c.domain AS domain
            ORDER BY c.created_at DESC
            LIMIT 25
            """,
            {"user_id": user_id},
        )
        by_id = {str(r["id"]): r for r in (neo_rows or []) if r.get("id")}
        for cid in weak_ids:
            if cid in by_id:
                _add_name(by_id[cid].get("name"))
                _add_name(by_id[cid].get("domain"))
        for r in neo_rows or []:
            _add_name(r.get("name"))
    except Exception as exc:  # noqa: BLE001 - best-effort personalization
        logger.warning("Feed: creative-cards neo4j concept lookup skipped", error=str(exc))

    spot_cards: list[dict] = []
    duel_cards: list[dict] = []
    seen_spot = list(excluded)
    seen_duel = list(excluded)

    while len(spot_cards) + len(duel_cards) < limit:
        progressed = False
        if len(spot_cards) <= len(duel_cards):
            s = creative_cards.select_spot_the_bug(concept_names, exclude_ids=seen_spot)
            if s is not None:
                seen_spot.append(s.id)
                spot_cards.append(s.as_dict())
                progressed = True
        if len(spot_cards) + len(duel_cards) < limit:
            d = creative_cards.select_tradeoff_duel(concept_names, exclude_ids=seen_duel)
            if d is not None:
                seen_duel.append(d.id)
                duel_cards.append(d.as_dict())
                progressed = True
        if not progressed:
            s = creative_cards.select_spot_the_bug(concept_names, exclude_ids=seen_spot)
            if s is not None:
                seen_spot.append(s.id)
                spot_cards.append(s.as_dict())
                progressed = True
        if not progressed:
            break

    cards: list[dict] = []
    for idx in range(max(len(spot_cards), len(duel_cards))):
        if idx < len(spot_cards):
            cards.append(spot_cards[idx])
        if idx < len(duel_cards):
            cards.append(duel_cards[idx])

    return {
        "cards": cards,
        "spot_the_bug": spot_cards,
        "tradeoff_duel": duel_cards,
        "matched_concepts": concept_names[:10],
        "total": len(cards),
    }


@router.post("/spot-the-bug-grade")
async def grade_spot_the_bug_card(
    body: SpotTheBugGradeRequest,
    current_user: dict = Depends(get_current_user),
):
    """Grade a Spot-the-Bug selection and record `quiz` evidence into knowledge_map."""
    card = next((c for c in creative_cards.SPOT_THE_BUG_CARDS if c.id == body.card_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Spot-the-bug card not found: {body.card_id}")

    graded = creative_cards.grade_spot_the_bug(card, body.selected_line)
    user_id = str(current_user["id"])

    concept_id: Optional[str] = None
    try:
        neo4j_client = await get_neo4j_client()
        concept = km.match_concept(card.concept_name, await km._user_concepts(neo4j_client, user_id))
        concept_id = concept["id"] if concept else None
    except Exception as exc:  # noqa: BLE001 - concept lookup is best-effort; skill_name still records
        logger.warning("Feed: spot-the-bug concept match skipped", error=str(exc))

    pg_client = await get_postgres_client()
    ev = graded["evidence"]
    await km.add_evidence(
        pg_client,
        user_id,
        kind="quiz",
        signal=ev["score"],
        concept_id=concept_id,
        skill_name=card.concept_name,
        source_id=f"spot_the_bug:{card.id}",
        detail=ev.get("metadata"),
    )

    return {
        **graded,
        "card_id": card.id,
        "concept_name": card.concept_name,
        "concept_id": concept_id,
        "recorded": True,
    }


class TradeoffDuelPickRequest(BaseModel):
    card_id: str = Field(..., max_length=80)
    choice: Literal["a", "b"]


# A pick matching the recommended option is good evidence; the other option is a miss, but a
# defensible one (each card says when the other option wins), so it is not scored as a failure.
_DUEL_MATCH_SIGNAL = 0.8
_DUEL_OTHER_SIGNAL = 0.4


@router.post("/tradeoff-duel-pick")
async def pick_tradeoff_duel(
    body: TradeoffDuelPickRequest,
    current_user: dict = Depends(get_current_user),
):
    """Record a Tradeoff Duel pick as `quiz` evidence ("depends" cards accept either option)."""
    card = next((c for c in creative_cards.TRADEOFF_DUEL_CARDS if c.id == body.card_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Tradeoff duel card not found: {body.card_id}")
    matched = card.recommended == "depends" or card.recommended == body.choice
    signal = _DUEL_MATCH_SIGNAL if matched else _DUEL_OTHER_SIGNAL
    user_id = str(current_user["id"])

    concept_id: Optional[str] = None
    try:
        concept = km.match_concept(card.concept_name, await km._user_concepts(await get_neo4j_client(), user_id))
        concept_id = concept["id"] if concept else None
    except Exception as exc:  # noqa: BLE001 - concept lookup is best-effort; skill_name still records
        logger.warning("Feed: tradeoff duel concept match skipped", error=str(exc))

    await km.add_evidence(
        await get_postgres_client(), user_id, kind="quiz", signal=signal, concept_id=concept_id,
        skill_name=card.concept_name, source_id=f"tradeoff_duel:{card.id}",
        detail={"choice": body.choice, "recommended": card.recommended, "matched": matched},
    )
    return {"card_id": card.id, "matched": matched, "recommended": card.recommended,
            "signal": signal, "concept_id": concept_id, "recorded": True}


@router.post("/review")
async def record_review(
    item_id: str,
    item_type: str,
    difficulty: DifficultyLevel,
    current_user: dict = Depends(get_current_user),
    response_time_ms: Optional[int] = None,
    concept_id: Optional[str] = None,
):
    """
    Record a review for a feed item.

    This updates the spaced repetition data of the item's *concept* and
    calculates its next review date. Clients should send `concept_id`;
    without it the concept is looked up from the quiz/flashcard id (or the
    id is accepted if it already is one of the user's concepts).

    Difficulty levels:
    - again: Complete failure, reset to beginning
    - hard: Correct but difficult
    - good: Correct with some hesitation
    - easy: Perfect recall
    """
    try:
        pg_client = await get_postgres_client()
        user_id = str(current_user["id"])
        try:
            neo4j_client = await get_neo4j_client()
        except Exception:  # noqa: BLE001 - resolution can still use Postgres
            neo4j_client = None
        try:
            target, resolved_by = await resolve_review_concept(pg_client, neo4j_client, user_id, item_id, concept_id)
        except UnresolvableReviewTarget as e:
            # Cards without a concept (screenshots/uploads, on-the-fly cards, old offline-queued
            # reviews) have nothing to schedule. Answer 200 "skipped" rather than an error: the iOS
            # offline queue retries every failed review, so a 4xx here would loop forever.
            logger.warning("Feed: review skipped, no concept", item_id=item_id, item_type=item_type)
            return {"status": "skipped", "reason": str(e), "concept_id": None}

        algorithm = _resolve_user_sr_algorithm(current_user)
        sr_service = SpacedRepetitionService(pg_client, algorithm=algorithm)

        review = ReviewResult(
            item_id=target,
            item_type=item_type,
            user_id=user_id,
            difficulty=difficulty,
            response_time_ms=response_time_ms,
        )

        updated_data = await sr_service.record_review(review)
        try:
            from backend.services.knowledge_map import REVIEW_SIGNAL, add_evidence

            await add_evidence(pg_client, user_id, kind="review", signal=REVIEW_SIGNAL[difficulty.value],
                               concept_id=target, source_id=item_id, detail={"item_type": item_type})
        except Exception as e:  # noqa: BLE001 - the review itself is already recorded
            logger.warning("Feed: review evidence not recorded", error=str(e))

        return {
            "status": "recorded",
            "concept_id": target,
            "resolved_by": resolved_by,
            "next_review": updated_data.next_review.isoformat(),
            "new_interval_days": updated_data.interval,
            "easiness_factor": updated_data.easiness_factor,
            "streak": updated_data.correct_streak,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Feed: Error recording review", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=UserStats)
async def get_user_stats(
    current_user: dict = Depends(get_current_user),
):
    """
    Get user's learning statistics.
    
    Includes:
    - Total concepts and notes
    - Streak days
    - Accuracy rate
    - Due items today
    - Progress by domain
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        feed_service = FeedService(pg_client, neo4j_client)
        sr_service = SpacedRepetitionService(pg_client)
        
        user_id = str(current_user["id"])
        
        # Get various stats
        sr_stats = await sr_service.get_user_stats(user_id)
        streak = await feed_service.get_user_streak(user_id)
        completed_today = await feed_service.get_completed_today(user_id)
        daily_goal = await feed_service.get_daily_goal(user_id)
        domains = await feed_service.get_user_domains(user_id)
        
        # Get concept count from Neo4j
        total_concepts = 0
        try:
            result = await neo4j_client.execute_query(
                "MATCH (c:Concept {user_id: $user_id}) RETURN count(c) as count",
                {"user_id": user_id},
            )
            if result:
                total_concepts = result[0].get("count", 0)
        except Exception as e:
            logger.warning("Failed to get concept count", error=str(e))
        
        # Get note count
        total_notes = 0
        try:
            result = await pg_client.execute_query(
                "SELECT COUNT(*) as count FROM notes WHERE user_id = :user_id",
                {"user_id": user_id},
            )
            if result:
                total_notes = result[0].get("count", 0)
        except Exception as e:
            logger.warning("Failed to get note count", error=str(e))
        
        # Get domain mastery and daily activity
        domain_progress = await feed_service.get_domain_mastery(user_id)
        daily_activity = await feed_service.get_daily_activity(user_id)
        
        return UserStats(
            user_id=user_id,
            total_concepts=total_concepts,
            total_notes=total_notes,
            total_reviews=sr_stats.get("total_reviews", 0),
            streak_days=streak,
            accuracy_rate=sr_stats.get("average_mastery", 0),
            domain_progress=domain_progress,
            daily_activity=daily_activity,
            due_today=sr_stats.get("due_today", 0),
            completed_today=completed_today,
            daily_goal=daily_goal,
            overdue=sr_stats.get("overdue", 0),
        )
        
    except Exception as e:
        logger.error("Feed: Error getting stats", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/saved")
async def get_saved_items(
    current_user: dict = Depends(get_current_user),
):
    """Get all saved quizzes and flashcards for the user."""
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        user_id = str(current_user["id"])

        # Fetch saved quizzes
        saved_quizzes = await pg_client.execute_query(
            """
            SELECT id, question_text, question_type, options_json, correct_answer, explanation, concept_id, source_url, created_at
            FROM quizzes
            WHERE user_id = :uid AND is_saved = TRUE
            ORDER BY created_at DESC
            """,
            {"uid": user_id},
        )

        # Fetch saved flashcards
        saved_flashcards = await pg_client.execute_query(
            """
            SELECT id, front_content, back_content, concept_id, created_at
            FROM flashcards
            WHERE user_id = :uid AND is_saved = TRUE
            ORDER BY created_at DESC
            """,
            {"uid": user_id},
        )

        # Resolve concept names from Neo4j
        concept_ids = list(
            set(
                q.get("concept_id")
                for q in (saved_quizzes + saved_flashcards)
                if q.get("concept_id")
            )
        )
        concept_map = {}
        if concept_ids:
            try:
                result = await neo4j_client.execute_query(
                    "MATCH (c:Concept {user_id: $user_id}) WHERE c.id IN $ids RETURN c.id as id, c.name as name",
                    {"ids": concept_ids, "user_id": user_id},
                )
                for row in result:
                    concept_map[row["id"]] = row["name"]
            except Exception:
                pass

        items = []

        for q in saved_quizzes:
            opts = q.get("options_json")
            if isinstance(opts, str):
                opts = json.loads(opts)
            items.append({
                "id": q["id"],
                "type": q.get("question_type", "mcq"),
                "question_text": q["question_text"],
                "options": opts or [],
                "correct_answer": q.get("correct_answer", ""),
                "explanation": q.get("explanation", ""),
                "topic": concept_map.get(q.get("concept_id"), "General"),
                "source_url": q.get("source_url", ""),
                "created_at": str(q.get("created_at", "")),
                "item_category": "quiz",
            })

        for f in saved_flashcards:
            items.append({
                "id": f["id"],
                "type": "flashcard",
                "front_content": f["front_content"],
                "back_content": f["back_content"],
                "topic": concept_map.get(f.get("concept_id"), "General"),
                "created_at": str(f.get("created_at", "")),
                "item_category": "flashcard",
            })

        return {"items": items, "total": len(items)}

    except Exception as e:
        logger.error("Feed: Error getting saved items", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/quizzes")
async def get_quiz_history(
    current_user: dict = Depends(get_current_user),
):
    """Get history of quizzes AND flashcards created for the user."""
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        feed_service = FeedService(pg_client, neo4j_client)
        user_id = str(current_user["id"])

        quizzes = await feed_service.get_user_quizzes(user_id)

        # Also fetch flashcards
        flashcards = []
        try:
            flashcards = await pg_client.execute_query(
                """
                SELECT id, front_content, back_content, concept_id, created_at
                FROM flashcards
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT 50
                """,
                {"uid": user_id},
            )
        except Exception as e:
            logger.warning("Failed to fetch flashcards for history", error=str(e))

        # Collect all concept IDs
        concept_ids = list(set(
            q.get("concept_id") for q in (quizzes + flashcards) if q.get("concept_id")
        ))

        concept_map = {}
        if concept_ids:
            query = "MATCH (c:Concept {user_id: $user_id}) WHERE c.id IN $ids RETURN c.id as id, c.name as name"
            result = await neo4j_client.execute_query(query, {"ids": concept_ids, "user_id": user_id})
            for row in result:
                concept_map[row["id"]] = row["name"]

        # Annotate quizzes with topic
        for q in quizzes:
            q["topic"] = concept_map.get(q.get("concept_id"), "General Knowledge")

        # Convert flashcards to quiz-compatible format
        flashcard_items = []
        for f in flashcards:
            flashcard_items.append({
                "id": f["id"],
                "question_text": f.get("front_content", ""),
                "question_type": "flashcard",
                "options": [],
                "correct_answer": f.get("back_content", ""),
                "explanation": "",
                "concept_id": f.get("concept_id"),
                "topic": concept_map.get(f.get("concept_id"), "General Knowledge"),
                "created_at": str(f.get("created_at", "")),
                "front_content": f.get("front_content", ""),
                "back_content": f.get("back_content", ""),
            })

        # Merge and sort by created_at desc
        all_items = quizzes + flashcard_items
        all_items.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)

        return {"quizzes": all_items}

    except Exception as e:
        logger.error("Feed: Error getting quiz history", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/due-count")
async def get_due_count(
    current_user: dict = Depends(get_current_user),
):
    """Get quick count of items due for review."""
    try:
        pg_client = await get_postgres_client()
        sr_service = SpacedRepetitionService(pg_client)
        
        user_id = str(current_user["id"])
        stats = await sr_service.get_user_stats(user_id)
        
        return {
            "due_today": stats.get("due_today", 0),
            "overdue": stats.get("overdue", 0),
            "total": stats.get("due_today", 0) + stats.get("overdue", 0),
        }
        
    except Exception as e:
        logger.error("Feed: Error getting due count", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/{item_id}/like")
async def toggle_like(
    item_id: str,
    item_type: str,
    current_user: dict = Depends(get_current_user),
):
    """Toggle like status for a feed item (flashcard or quiz)."""
    try:
        pg_client = await get_postgres_client()
        user_id = str(current_user["id"])
        if item_type == "flashcard":
            table = "flashcards"
        elif item_type in ["mcq", "fill_blank", "quiz"]:
            table = "quizzes"
        else:
            raise HTTPException(status_code=400, detail=f"Invalid item_type: {item_type}")
        
        # Toggle the boolean
        await pg_client.execute_update(
            f"UPDATE {table} SET is_liked = NOT is_liked WHERE id = :item_id AND user_id = :user_id",
            {"item_id": item_id, "user_id": user_id}
        )
        
        # Return new status
        result = await pg_client.execute_query(
            f"SELECT is_liked FROM {table} WHERE id = :item_id AND user_id = :user_id",
            {"item_id": item_id, "user_id": user_id}
        )
        
        return {"id": item_id, "is_liked": result[0]["is_liked"] if result else False}
        
    except Exception as e:
        logger.error("Feed: Error toggling like", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{item_id}/save")
async def toggle_save(
    item_id: str,
    item_type: str,
    current_user: dict = Depends(get_current_user),
):
    """Toggle save status for a feed item (flashcard or quiz)."""
    try:
        pg_client = await get_postgres_client()
        user_id = str(current_user["id"])
        if item_type == "flashcard":
            table = "flashcards"
        elif item_type in ["mcq", "fill_blank", "quiz"]:
            table = "quizzes"
        else:
            raise HTTPException(status_code=400, detail=f"Invalid item_type: {item_type}")
        
        # Toggle the boolean
        await pg_client.execute_update(
            f"UPDATE {table} SET is_saved = NOT is_saved WHERE id = :item_id AND user_id = :user_id",
            {"item_id": item_id, "user_id": user_id}
        )
        
        # Return new status
        result = await pg_client.execute_query(
            f"SELECT is_saved FROM {table} WHERE id = :item_id AND user_id = :user_id",
            {"item_id": item_id, "user_id": user_id}
        )
        
        return {"id": item_id, "is_saved": result[0]["is_saved"] if result else False}
        
    except Exception as e:
        logger.error("Feed: Error toggling save", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Topic Quiz Generation
# ============================================================================


class TopicQuizRequest(BaseModel):
    """Request for generating a quiz on a topic."""
    user_id: str = "00000000-0000-0000-0000-000000000001"
    # Target pool size (internal preference, user doesn't specify)
    target_pool_size: int = 20
    force_research: bool = False
    allow_web_search: bool = True  # If False, skip Tavily web search and use only local content


class QuizQuestion(BaseModel):
    """A single quiz question."""
    question: str
    options: list[str]
    correct_answer: str
    explanation: str


@router.post("/quiz/topic/{topic_name}")
async def generate_topic_quiz(
    topic_name: str,
    request: TopicQuizRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate a quiz on a specific topic.
    
    Delegates to FeedService for batch generation.
    Returns a subset of questions for immediate practice.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        user_id = str(current_user["id"])
        
        feed_service = FeedService(pg_client, neo4j_client)
        
        return await feed_service.generate_content_batch(
            topic_name=topic_name,
            user_id=user_id,
            target_size=request.target_pool_size,
            force_research=request.force_research,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Quiz generation: Error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quiz/topic/{topic_name}/stream")
async def generate_topic_quiz_stream(
    topic_name: str,
    request: TopicQuizRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate a quiz on a topic with SSE streaming status updates.

    Streams events:
      - type: status  → progress updates (searching notes, web search, generating)
      - type: done    → final result with questions array
      - type: error   → error details
    """
    user_id = str(current_user["id"])

    async def event_stream():
        import json as _json

        def sse(data: dict) -> str:
            return f"data: {_json.dumps(data)}\n\n"

        try:
            pg_client = await get_postgres_client()
            neo4j_client = await get_neo4j_client()
            feed_service = FeedService(pg_client, neo4j_client)

            # Step 1: Resolve concept
            yield sse({"type": "status", "content": "🔍 Searching your knowledge graph..."})
            concept_id = None
            concept_def = ""
            try:
                concept_res = await neo4j_client.execute_query(
                    "MATCH (c:Concept {user_id: $user_id}) WHERE toLower(c.name) = toLower($name) "
                    "RETURN c.id as id, c.definition as def LIMIT 1",
                    {"name": topic_name, "user_id": user_id},
                )
                if concept_res:
                    concept_id = concept_res[0]["id"]
                    concept_def = concept_res[0].get("def") or ""
                    yield sse({"type": "status", "content": f"📚 Found concept: {topic_name}"})
                else:
                    yield sse({"type": "status", "content": f"🌐 Topic not in your graph yet — searching the web..."})
            except Exception:
                pass

            # Step 2: Check for existing quiz questions in DB
            yield sse({"type": "status", "content": "📋 Checking for existing questions..."})
            existing_questions = []
            try:
                existing = await pg_client.execute_query(
                    """
                    SELECT id, question_text, question_type, options_json, correct_answer, explanation, source_url
                    FROM quizzes
                    WHERE user_id = :uid
                      AND (concept_id = :cid OR LOWER(question_text) LIKE :topic_pattern)
                    ORDER BY created_at DESC
                    LIMIT 30
                    """,
                    {
                        "uid": user_id,
                        "cid": concept_id or "__none__",
                        "topic_pattern": f"%{topic_name.lower()}%",
                    },
                )
                for q in existing:
                    opts = q.get("options_json")
                    if isinstance(opts, str):
                        opts = _json.loads(opts)
                    existing_questions.append({
                        "id": str(q["id"]),
                        "question": q["question_text"],
                        "question_type": q.get("question_type", "mcq"),
                        "options": opts or [],
                        "correct_answer": q.get("correct_answer", ""),
                        "explanation": q.get("explanation", ""),
                        "source_url": q.get("source_url", ""),
                        "source": "notes",
                    })
            except Exception as e:
                logger.warning("Quiz stream: error fetching existing", error=str(e))

            if existing_questions:
                yield sse({"type": "status", "content": f"✅ Found {len(existing_questions)} existing questions from your notes"})

            # Step 3: Web research via Tavily (only if user consented)
            research_result = {}
            if request.allow_web_search:
                yield sse({"type": "status", "content": "🌐 Searching the web for quiz material..."})
                try:
                    from backend.agents.research_agent import WebResearchAgent
                    research_agent = WebResearchAgent(neo4j_client, pg_client)
                    research_result = await research_agent.research_topic(
                        topic=topic_name,
                        user_id=user_id,
                        force=request.force_research,
                    )
                    if research_result.get("summary"):
                        yield sse({"type": "status", "content": "📝 Web research complete — synthesising material..."})
                    else:
                        yield sse({"type": "status", "content": "📝 Using available resources..."})
                except Exception as e:
                    logger.warning("Quiz stream: research failed", error=str(e))
                    yield sse({"type": "status", "content": "⚠️ Web search unavailable — using local resources"})
            else:
                yield sse({"type": "status", "content": "📚 Using your notes only (web search skipped)"})

            # Step 4: Generate new questions
            need_new = max(0, request.target_pool_size - len(existing_questions))
            new_questions = []

            if need_new > 0:
                # If we don't have a concept_id (i.e. new topic), create it now so we can save questions
                if not concept_id:
                     try:
                        yield sse({"type": "status", "content": f"🌱 Creating new concept: {topic_name}..."})
                        def_text = research_result.get("summary") or f"Automatically generated concept for {topic_name}"
                        new_concept_res = await neo4j_client.create_concept(
                            name=topic_name,
                            definition=def_text[:1000], # Limit length
                            domain="General",
                            complexity_score=0.5,
                            user_id=user_id,
                            confidence=0.6 if research_result else 0.3
                        )
                        if new_concept_res and new_concept_res.get("c"):
                            concept_id = new_concept_res["c"].get("id")
                            concept_def = new_concept_res["c"].get("definition")
                            yield sse({"type": "status", "content": "✨ Concept created successfully"})
                     except Exception as e:
                        logger.error("Quiz stream: Failed to create concept", error=str(e))
                        # We can't save to DB without concept_id, so we must abort DB saving for these items
                        # or skip this batch. But let's verify if we can continue.
                        # If we continue, the INSERT below will fail.
                        pass

                yield sse({"type": "status", "content": f"🧠 Generating {need_new} new questions..."})
                try:
                    content_text = concept_def + "\n" + (research_result.get("summary") or "")
                    new_items = await feed_service.content_generator.generate_mixed_batch(
                        topic=topic_name,
                        definition=content_text[:6000],
                        count=need_new,
                    )

                    for item in new_items:
                        itype = item.get("type")
                        content = item.get("content")
                        if not content:
                            continue

                        item_id = str(uuid.uuid4())

                        # Only return quiz-type items (MCQ, fill_blank, code_challenge)
                        if itype in ["mcq", "fill_blank", "code_challenge"]:
                            try:
                                await pg_client.execute_update(
                                    """
                                    INSERT INTO quizzes (id, user_id, concept_id, question_text, question_type,
                                                        options_json, correct_answer, explanation, created_at, source,
                                                        language, initial_code)
                                    VALUES (:id, :uid, :cid, :q_text, :q_type, :opts, :correct, :exp, NOW(), 'batch_gen', :lang, :icode)
                                    """,
                                    {
                                        "id": item_id,
                                        "uid": user_id,
                                        "cid": concept_id,
                                        "q_text": content.get("question") or content.get("instruction") or content.get("sentence"),
                                        "q_type": itype,
                                        "opts": _json.dumps(content.get("options", [])),
                                        "correct": str(content.get("is_correct") or content.get("solution_code") or content.get("answers", [""])[0]),
                                        "exp": content.get("explanation", ""),
                                        "lang": content.get("language"),
                                        "icode": content.get("initial_code"),
                                    },
                                )
                            except Exception as e:
                                logger.warning("Quiz stream: save failed", error=str(e))

                            new_questions.append({
                                "id": item_id,
                                "question": content.get("question") or content.get("instruction") or content.get("sentence") or "",
                                "question_type": itype,
                                "options": content.get("options", []),
                                "correct_answer": str(content.get("is_correct") or content.get("solution_code") or content.get("answers", [""])[0]),
                                "explanation": content.get("explanation", ""),
                                "source": "web",
                            })
                        elif itype == "term_card":
                            # Save flashcards too
                            try:
                                await pg_client.execute_update(
                                    """
                                    INSERT INTO flashcards (id, user_id, concept_id, front_content, back_content, created_at, source)
                                    VALUES (:id, :uid, :cid, :front, :back, NOW(), 'batch_gen')
                                    """,
                                    {
                                        "id": item_id,
                                        "uid": user_id,
                                        "cid": concept_id,
                                        "front": content.get("front"),
                                        "back": content.get("back"),
                                    },
                                )
                            except Exception:
                                pass

                    yield sse({"type": "status", "content": f"✨ Generated {len(new_questions)} new questions"})

                except Exception as e:
                    logger.error("Quiz stream: generation failed", error=str(e))
                    yield sse({"type": "status", "content": "⚠️ Question generation had issues — showing available questions"})

            # Combine: notes-based first, then web-scraped
            all_questions = existing_questions + new_questions
            total = len(all_questions)

            yield sse({
                "type": "done",
                "questions": all_questions,
                "topic": topic_name,
                "total": total,
                "from_notes": len(existing_questions),
                "from_web": len(new_questions),
            })

        except Exception as e:
            logger.error("Quiz stream: Fatal error", error=str(e))
            yield sse({"type": "error", "content": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/resources/{concept_name}")
async def get_resources_for_concept(
    concept_name: str,
    current_user: dict = Depends(get_current_user),
    resource_type: Optional[str] = Query(default=None),
):
    """
    Get all resources linked to a concept.
    
    Usage: "Pull my resources for cross entropy"
    
    Returns notes, saved responses, and concept definitions
    related to the specified concept name.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        user_id = str(current_user["id"])
        resources = []
        
        # Get notes
        notes_query = """
        SELECT id, title, content_text, resource_type, source_url, created_at
        FROM notes
        WHERE user_id = :user_id
          AND (content_text ILIKE :pattern OR title ILIKE :pattern)
        """
        params = {
            "user_id": user_id,
            "pattern": f"%{concept_name}%",
        }
        
        if resource_type:
            notes_query += " AND resource_type = :resource_type"
            params["resource_type"] = resource_type
        
        notes_query += " ORDER BY created_at DESC LIMIT 20"
        
        notes = await pg_client.execute_query(notes_query, params)
        
        for note in notes:
            resources.append({
                "type": "note",
                "id": str(note.get("id")),
                "title": note.get("title") or "Untitled",
                "preview": note.get("content_text", "")[:200] + "...",
                "resource_type": note.get("resource_type"),
                "source_url": note.get("source_url"),
                "created_at": str(note.get("created_at")),
            })
        
        # Get saved responses
        saved_query = """
        SELECT sr.id, sr.topic, sr.content, sr.created_at
        FROM saved_responses sr
        WHERE sr.user_id = :user_id
          AND (sr.content ILIKE :pattern OR sr.topic ILIKE :pattern)
        ORDER BY sr.created_at DESC
        LIMIT 10
        """
        
        try:
            saved = await pg_client.execute_query(
                saved_query,
                {"user_id": user_id, "pattern": f"%{concept_name}%"}
            )
            
            for s in saved:
                resources.append({
                    "type": "saved_response",
                    "id": str(s.get("id")),
                    "title": s.get("topic") or "Saved Response",
                    "preview": s.get("content", "")[:200] + "...",
                    "created_at": str(s.get("created_at")),
                })
        except Exception as e:
            logger.debug("saved_responses table not available", error=str(e))
        
        # Get concepts from Neo4j
        concepts_query = """
        MATCH (c:Concept {user_id: $user_id})
        WHERE toLower(c.name) CONTAINS toLower($name)
        OPTIONAL MATCH (n:NoteSource {user_id: $user_id})-[:EXPLAINS]->(c)
        RETURN c.id as id, c.name as name, c.definition as definition,
               c.domain as domain, collect(n.id) as linked_notes
        LIMIT 10
        """
        
        concepts = await neo4j_client.execute_query(
            concepts_query,
            {"name": concept_name, "user_id": user_id}
        )
        
        for concept in concepts:
            resources.append({
                "type": "concept",
                "id": concept.get("id"),
                "title": concept.get("name"),
                "preview": concept.get("definition") or "No definition",
                "domain": concept.get("domain"),
                "linked_notes": concept.get("linked_notes", []),
            })
        
        logger.info(
            "get_resources_for_concept",
            concept=concept_name,
            num_resources=len(resources),
        )
        
        return {
            "concept": concept_name,
            "resources": resources,
            "total": len(resources),
        }
        
    except Exception as e:
        logger.error("Feed: Error getting resources", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/schedule")
async def get_active_recall_schedule(
    current_user: dict = Depends(get_current_user),
    days: int = Query(default=30, le=60),
):
    """
    Get upcoming review schedule for the calendar.
    Returns counts of items due per day, plus topic names.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        sr_service = SpacedRepetitionService(pg_client)

        return await sr_service.get_upcoming_schedule_with_topics(
            str(current_user["id"]), neo4j_client, days
        )

    except Exception as e:
        logger.error("Feed: Error getting schedule", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
