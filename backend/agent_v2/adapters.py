"""Concrete production adapters implementing MemoryFacade and LLMGateway black boxes."""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent_v2.protocols import BridgeProposalBatch, NoteChunk
from backend.config.llm import DEFAULT_FAST_MODEL, get_fast_model
from backend.db.postgres_client import PostgresClient

logger = structlog.get_logger()


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


class GeminiLLMGateway:
    """Black-box LLM gateway that enforces structured output and surfaces errors explicitly."""

    def __init__(self, model_name: str = DEFAULT_FAST_MODEL):
        self._model_name = model_name

    async def propose_bridges(
        self,
        *,
        note_title: str,
        note_chunks: list[NoteChunk],
        candidate_chunks: list[NoteChunk],
        concept_names: list[str],
    ) -> tuple[BridgeProposalBatch, dict[str, Any]]:
        llm = get_fast_model(temperature=0.0).with_structured_output(
            BridgeProposalBatch,
            include_raw=True,
        )

        system_prompt = (
            "You are GraphRecall's cross-note synthesis auditor.\n"
            "Given chunks from a newly ingested note and chunks from older notes, propose at most 3 "
            "meaningful cross-note conceptual bridges or contradictions.\n"
            "STRICT PROVENANCE RULE ('no quote, no edge'):\n"
            "- source_chunk_id MUST belong to the new note.\n"
            "- target_chunk_id MUST belong to an older note.\n"
            "- source_quote MUST be an exact, verbatim substring (>= 12 chars) copied from source_chunk_id.\n"
            "- target_quote MUST be an exact, verbatim substring (>= 12 chars) copied from target_chunk_id.\n"
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
