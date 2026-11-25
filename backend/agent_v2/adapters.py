"""Concrete production adapters implementing MemoryFacade and LLMGateway black boxes."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, Optional

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent_v2.protocols import (
    BridgeProposalBatch,
    ConceptReviewContext,
    DailyBriefingDraft,
    NoteChunk,
    RemedialDiagnosis,
    UserLearningDigest,
)
from backend.config.llm import DEFAULT_FAST_MODEL, get_fast_model
from backend.db.postgres_client import PostgresClient

logger = structlog.get_logger()


class AsyncRateLimiter:
    """Async minimum-interval rate limiter to protect shared LLM free-tier quotas."""

    def __init__(
        self,
        max_rpm: float = 12.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._max_rpm = float(max_rpm)
        self._min_interval_s = (60.0 / self._max_rpm) if self._max_rpm > 0 else 0.0
        self._clock = clock
        self._sleeper = sleeper
        self._lock = asyncio.Lock()
        self._last_call_at: Optional[float] = None

    @property
    def min_interval_s(self) -> float:
        return self._min_interval_s

    async def acquire(self) -> float:
        """Wait if needed to respect `max_rpm`. Returns seconds slept."""
        if self._min_interval_s <= 0:
            return 0.0
        async with self._lock:
            now = self._clock()
            slept = 0.0
            if self._last_call_at is not None:
                wait = self._min_interval_s - (now - self._last_call_at)
                if wait > 0:
                    await self._sleeper(wait)
                    slept = wait
                    now = self._clock()
            self._last_call_at = now
            return slept


class PostgresMemoryFacade:
    """Black-box read-only retriever over Postgres chunks for cross-note synthesis."""

    def __init__(self, pg: PostgresClient):
        self._pg = pg

    async def fetch_note_and_related_chunks(
        self,
        user_id: str,
        note_id: str,
        concept_names: list[str],
        *,
        limit: int = 12,
    ) -> list[NoteChunk]:
        note_rows = await self._pg.execute_query(
            """
            SELECT c.id AS chunk_id, c.note_id, COALESCE(n.title, 'Untitled') AS note_title, c.content
            FROM chunks c
            JOIN notes n ON c.note_id = n.id
            WHERE n.user_id = CAST(:user_id AS uuid)
              AND c.note_id = CAST(:note_id AS uuid)
            ORDER BY COALESCE(c.chunk_index, 0) ASC
            LIMIT :lim
            """,
            {"user_id": user_id, "note_id": note_id, "lim": max(limit, 6)},
        )

        # Prefer vector similarity against the note's first embedded chunk; fall back to recent chunks.
        other_rows = await self._pg.execute_query(
            """
            WITH seed AS (
                SELECT c.embedding
                FROM chunks c
                JOIN notes n ON c.note_id = n.id
                WHERE n.user_id = CAST(:user_id AS uuid)
                  AND c.note_id = CAST(:note_id AS uuid)
                  AND c.embedding IS NOT NULL
                LIMIT 1
            )
            SELECT c.id AS chunk_id, c.note_id, COALESCE(n.title, 'Untitled') AS note_title, c.content
            FROM chunks c
            JOIN notes n ON c.note_id = n.id
            LEFT JOIN seed s ON TRUE
            WHERE n.user_id = CAST(:user_id AS uuid)
              AND c.note_id <> CAST(:note_id AS uuid)
            ORDER BY
                CASE WHEN s.embedding IS NOT NULL AND c.embedding IS NOT NULL
                     THEN c.embedding <=> s.embedding
                     ELSE 1.0
                END ASC,
                c.created_at DESC
            LIMIT :lim
            """,
            {"user_id": user_id, "note_id": note_id, "lim": limit},
        )

        chunks: list[NoteChunk] = []
        for row in [*note_rows, *other_rows]:
            chunks.append(
                NoteChunk(
                    chunk_id=str(row["chunk_id"]),
                    note_id=str(row["note_id"]),
                    note_title=str(row["note_title"]),
                    content=str(row["content"]),
                )
            )
        return chunks

    async def fetch_concept_review_context(
        self,
        user_id: str,
        concept_id: str,
        concept_name: str,
        *,
        note_id: Optional[str] = None,
        limit: int = 6,
    ) -> ConceptReviewContext:
        rows: list[dict[str, Any]] = []
        if note_id:
            rows = await self._pg.execute_query(
                """
                SELECT c.id AS chunk_id, c.note_id, COALESCE(n.title, 'Untitled') AS note_title, c.content
                FROM chunks c
                JOIN notes n ON c.note_id = n.id
                WHERE n.user_id = CAST(:user_id AS uuid)
                  AND c.note_id = CAST(:note_id AS uuid)
                ORDER BY COALESCE(c.chunk_index, 0) ASC
                LIMIT :lim
                """,
                {"user_id": user_id, "note_id": note_id, "lim": limit},
            )
        if not rows and concept_name.strip():
            rows = await self._pg.execute_query(
                """
                SELECT c.id AS chunk_id, c.note_id, COALESCE(n.title, 'Untitled') AS note_title, c.content
                FROM chunks c
                JOIN notes n ON c.note_id = n.id
                WHERE n.user_id = CAST(:user_id AS uuid)
                  AND c.content ILIKE :pattern
                ORDER BY c.created_at DESC
                LIMIT :lim
                """,
                {"user_id": user_id, "pattern": f"%{concept_name.strip()}%", "lim": limit},
            )
        chunks = [
            NoteChunk(
                chunk_id=str(r["chunk_id"]),
                note_id=str(r["note_id"]),
                note_title=str(r["note_title"]),
                content=str(r["content"]),
            )
            for r in rows
        ]
        # Postgres does not authoritatively track PREREQUISITE_OF edges; leave flag explicit.
        return ConceptReviewContext(
            concept_id=concept_id,
            concept_name=concept_name,
            prerequisites=[],
            has_prerequisite_edges=False,
            chunks=chunks,
        )

    async def fetch_learning_digest(
        self,
        user_id: str,
        *,
        window_days: int = 7,
        limit: int = 8,
    ) -> UserLearningDigest:
        note_count_rows = await self._pg.execute_query(
            """
            SELECT COUNT(*) AS cnt
            FROM notes
            WHERE user_id = CAST(:user_id AS uuid)
              AND created_at >= NOW() - make_interval(days => :days)
            """,
            {"user_id": user_id, "days": max(int(window_days), 1)},
        )
        recent_notes_count = int(note_count_rows[0]["cnt"]) if note_count_rows else 0

        chunk_rows = await self._pg.execute_query(
            """
            SELECT c.id AS chunk_id, c.note_id, COALESCE(n.title, 'Untitled') AS note_title, c.content
            FROM chunks c
            JOIN notes n ON c.note_id = n.id
            WHERE n.user_id = CAST(:user_id AS uuid)
            ORDER BY c.created_at DESC
            LIMIT :lim
            """,
            {"user_id": user_id, "lim": limit},
        )
        sample_chunks = [
            NoteChunk(
                chunk_id=str(r["chunk_id"]),
                note_id=str(r["note_id"]),
                note_title=str(r["note_title"]),
                content=str(r["content"]),
            )
            for r in chunk_rows
        ]

        due_concepts: list[str] = []
        lapsed_concepts: list[str] = []
        try:
            due_rows = await self._pg.execute_query(
                """
                SELECT concept_id, score
                FROM proficiency_scores
                WHERE user_id = CAST(:user_id AS uuid)
                  AND next_review_due IS NOT NULL AND next_review_due <= NOW()  -- same rule as the feed
                ORDER BY score ASC, next_review_due ASC
                LIMIT :lim
                """,
                {"user_id": user_id, "lim": limit},
            )
            for row in due_rows:
                cid = str(row["concept_id"])
                due_concepts.append(cid)
                if float(row.get("score") or 0.0) < 0.4:
                    lapsed_concepts.append(cid)
        except Exception as exc:
            logger.debug("agent_v2.digest_proficiency_unavailable", user_id=user_id, error=str(exc))

        return UserLearningDigest(
            recent_notes_count=recent_notes_count,
            due_concepts=due_concepts,
            lapsed_concepts=lapsed_concepts,
            sample_chunks=sample_chunks,
        )


class GeminiLLMGateway:
    """Black-box LLM gateway that enforces structured output, rate limits, and explicit errors."""

    def __init__(
        self,
        model_name: str = DEFAULT_FAST_MODEL,
        *,
        rate_limiter: Optional[AsyncRateLimiter] = None,
    ):
        self._model_name = model_name
        default_rpm = float(os.getenv("AGENT_V2_MAX_RPM", "12.0"))
        self._rate_limiter = rate_limiter or AsyncRateLimiter(max_rpm=default_rpm)

    async def _invoke_structured(
        self,
        schema: type,
        system_prompt: str,
        human_prompt: str,
    ) -> tuple[Any, dict[str, Any]]:
        await self._rate_limiter.acquire()
        llm = get_fast_model(temperature=0.0).with_structured_output(
            schema,
            include_raw=True,
        )
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ])

        parsing_error = response.get("parsing_error") if isinstance(response, dict) else None
        parsed = response.get("parsed") if isinstance(response, dict) else response
        raw_msg = response.get("raw") if isinstance(response, dict) else None

        if parsing_error is not None or parsed is None:
            raise RuntimeError(f"LLM structured output failed: {parsing_error}")

        usage = getattr(raw_msg, "usage_metadata", None) or {}
        meta = {
            "model": self._model_name,
            "input_tokens": int(usage.get("input_tokens", 0)),
            "output_tokens": int(usage.get("output_tokens", 0)),
        }
        return parsed, meta

    async def propose_bridges(
        self,
        *,
        note_title: str,
        note_chunks: list[NoteChunk],
        candidate_chunks: list[NoteChunk],
        concept_names: list[str],
    ) -> tuple[BridgeProposalBatch, dict[str, Any]]:
        system_prompt = (
            "You are GraphRecall's cross-note synthesis auditor.\n"
            "Given chunks from a newly ingested note and chunks from older notes, propose at most 3 "
            "meaningful cross-note conceptual bridges or contradictions.\n"
            "STRICT PROVENANCE RULE ('no quote, no edge'):\n"
            "- source_chunk_id MUST belong to the new note.\n"
            "- target_chunk_id MUST belong to an older note.\n"
            "- source_quote MUST be an exact, verbatim substring (>= 12 chars, >= 2 content words) from source_chunk_id.\n"
            "- target_quote MUST be an exact, verbatim substring (>= 12 chars, >= 2 content words) from target_chunk_id.\n"
            "If no genuine cross-note link exists, return an empty list."
        )

        new_block = "\n".join(
            f"[{c.chunk_id}] ({c.note_title}): {c.content[:1200]}"
            for c in note_chunks
        )
        old_block = "\n".join(
            f"[{c.chunk_id}] ({c.note_title}): {c.content[:1200]}"
            for c in candidate_chunks
        )
        concepts_str = ", ".join(concept_names) if concept_names else "(none extracted)"

        human_prompt = (
            f"New note title: {note_title or 'Untitled'}\n"
            f"Extracted concepts: {concepts_str}\n\n"
            f"### New Note Chunks\n{new_block}\n\n"
            f"### Existing Note Chunks\n{old_block}"
        )
        return await self._invoke_structured(BridgeProposalBatch, system_prompt, human_prompt)

    async def diagnose_review_lapse(
        self,
        *,
        context: ConceptReviewContext,
        lapse_count: int,
    ) -> tuple[RemedialDiagnosis, dict[str, Any]]:
        prereq_note = (
            f"Known prerequisites: {', '.join(context.prerequisites)}"
            if context.has_prerequisite_edges and context.prerequisites
            else "Prerequisite graph edges are unavailable/empty; rely strictly on note chunks below and set missing_prerequisite=null unless directly stated."
        )
        system_prompt = (
            "You are GraphRecall's spaced-repetition remediation tutor.\n"
            "Diagnose why the learner struggled on this concept and write a concise targeted prompt.\n"
            "STRICT PROVENANCE RULE ('no quote, no insight'):\n"
            "- source_chunk_id MUST match one of the provided chunk IDs.\n"
            "- source_quote MUST be an exact, verbatim substring (>= 12 chars, >= 2 content words) from that chunk."
        )
        chunks_block = "\n".join(
            f"[{c.chunk_id}] ({c.note_title}): {c.content[:1200]}"
            for c in context.chunks
        )
        human_prompt = (
            f"Lapsed concept: {context.concept_name} (id={context.concept_id}, lapse_count={lapse_count})\n"
            f"{prereq_note}\n\n"
            f"### Supporting Note Chunks\n{chunks_block}"
        )
        return await self._invoke_structured(RemedialDiagnosis, system_prompt, human_prompt)

    async def compose_daily_briefing(
        self,
        *,
        digest: UserLearningDigest,
        window_days: int,
    ) -> tuple[DailyBriefingDraft, dict[str, Any]]:
        system_prompt = (
            "You are GraphRecall's daily study briefing synthesizer.\n"
            "Summarize key themes and due/lapsed focus priorities grounded directly in the learner's notes.\n"
            "STRICT PROVENANCE RULE ('no quote, no briefing'):\n"
            "- cited_chunk_id MUST match one of the provided chunk IDs.\n"
            "- cited_quote MUST be an exact, verbatim substring (>= 12 chars, >= 2 content words) from that chunk."
        )
        chunks_block = "\n".join(
            f"[{c.chunk_id}] ({c.note_title}): {c.content[:1200]}"
            for c in digest.sample_chunks
        )
        human_prompt = (
            f"Window: last {window_days} days\n"
            f"Recent notes count: {digest.recent_notes_count}\n"
            f"Due concepts: {', '.join(digest.due_concepts) or '(none)'}\n"
            f"Lapsed concepts: {', '.join(digest.lapsed_concepts) or '(none)'}\n\n"
            f"### Sample Note Chunks\n{chunks_block}"
        )
        return await self._invoke_structured(DailyBriefingDraft, system_prompt, human_prompt)
