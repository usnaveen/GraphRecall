"""Route a chat message without an LLM call when the trained classifier is confident.

Modes (env ``CHAT_INTENT_ROUTER``):
  llm     - previous behaviour: one fast-model structured-output call for intent + entities.
  shadow  - the LLM decides; the classifier's guess is logged next to it (collects agreement data).
  model   - default. The classifier decides when its confidence >= threshold; entities come from
            matching the user's own concept names in the message. Falls back to the LLM when the
            classifier is unsure, the artifact is missing, or a quiz request names no known topic.
Every decision is written to ``intent_decisions`` (best effort; never blocks or fails a chat).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Optional

import structlog

from backend.services.intent_router.model import Prediction, get_classifier

logger = structlog.get_logger()

MENTION_QUERY = """
MATCH (c:Concept)
WHERE c.user_id = $user_id
  AND size(c.name) >= 3
  AND $q CONTAINS toLower(c.name)
  AND coalesce(c.confidence, 0.8) >= 0.4
RETURN c.name AS name
ORDER BY size(c.name) DESC
LIMIT 25
"""


def router_mode() -> str:
    mode = os.getenv("CHAT_INTENT_ROUTER", "model").strip().lower()
    return mode if mode in {"llm", "shadow", "model"} else "model"


def confidence_threshold(default: float) -> float:
    try:
        return float(os.getenv("CHAT_INTENT_THRESHOLD", default))
    except ValueError:
        return default


def classify(query: str) -> Optional[Prediction]:
    clf = get_classifier()
    if clf is None:
        return None
    try:
        return clf.predict(query)
    except Exception as e:  # noqa: BLE001
        logger.warning("intent_router: classifier failed", error=str(e))
        return None


def model_version() -> Optional[str]:
    clf = get_classifier()
    return clf.version if clf else None


def default_threshold() -> float:
    clf = get_classifier()
    return clf.threshold if clf else 1.1


def filter_mentions(query: str, names: list[str], limit: int = 5) -> list[str]:
    """Keep concept names that occur in the query on word boundaries; drop names inside longer matches."""
    q = query.lower()
    kept: list[str] = []
    for name in sorted(dict.fromkeys(n for n in names if n), key=len, reverse=True):
        low = name.lower()
        if not re.search(rf"(?<!\w){re.escape(low)}(?!\w)", q):
            continue
        if any(low in k.lower() for k in kept):
            continue
        kept.append(name)
        if len(kept) >= limit:
            break
    return kept


async def mentioned_concepts(user_id: str, query: str) -> list[str]:
    """Concept names from the user's own graph that the message mentions. No LLM."""
    try:
        from backend.db.neo4j_client import get_neo4j_client

        client = await get_neo4j_client()
        rows = await client.execute_query(MENTION_QUERY, {"user_id": user_id, "q": query.lower()})
        return filter_mentions(query, [str(r.get("name") or "") for r in rows or []])
    except Exception as e:  # noqa: BLE001
        logger.warning("intent_router: mention lookup failed", error=str(e))
        return []


async def _write_decision(row: dict[str, Any]) -> None:
    try:
        from backend.db.postgres_client import get_postgres_client

        pg = await get_postgres_client()
        await pg.execute_update(
            """
            INSERT INTO intent_decisions
              (user_id, query, intent, source, model_intent, model_confidence, model_version,
               llm_intent, entities, latency_ms)
            VALUES (CAST(:user_id AS uuid), :query, :intent, :source, :model_intent, :model_confidence,
                    :model_version, :llm_intent, CAST(:entities AS jsonb), :latency_ms)
            """,
            {**row, "entities": json.dumps(row.get("entities") or [])},
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("intent_router: decision not logged", error=str(e))


_PENDING: set[asyncio.Task] = set()


def log_decision(**row: Any) -> None:
    """Fire-and-forget insert; keeps a reference so the task isn't garbage-collected mid-flight."""
    if os.getenv("CHAT_INTENT_LOG", "1") == "0":
        return
    row.setdefault("model_intent", None)
    row.setdefault("model_confidence", None)
    row.setdefault("model_version", None)
    row.setdefault("llm_intent", None)
    row.setdefault("entities", [])
    row.setdefault("latency_ms", None)
    row["query"] = (row.get("query") or "")[:2000]
    try:
        task = asyncio.get_running_loop().create_task(_write_decision(row))
    except RuntimeError:
        return
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
