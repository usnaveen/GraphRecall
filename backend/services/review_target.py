"""Which concept a feed review should update.

Feed cards have their own id (a quiz or flashcard row id, or a random UUID for cards
generated on the fly) and carry the concept in a separate `concept_id`. The review
endpoint used to write the SM-2 schedule under the *card* id, so a concept's own
schedule never advanced. Resolution order:

1. an explicit `concept_id` from the client,
2. the concept of the quiz / flashcard row whose id the client sent,
3. the id itself, if it is already one of the user's Concept nodes (older clients),
otherwise there is no concept to schedule: the router answers 200 "skipped" (never an
error, since the iOS offline queue retries failed reviews) instead of creating a schedule
row for an id that isn't a concept.

Kept free of heavy imports so it can be unit-tested with fakes.
"""

from __future__ import annotations

from typing import Any, Optional


class UnresolvableReviewTarget(ValueError):
    pass


async def resolve_review_concept(
    pg_client: Any,
    neo4j_client: Optional[Any],
    user_id: str,
    item_id: str,
    concept_id: Optional[str] = None,
) -> tuple[str, str]:
    """Return (concept_id, how) where how ∈ {"explicit", "quiz", "flashcard", "concept"}."""
    if concept_id:
        return concept_id, "explicit"

    for table, how in (("quizzes", "quiz"), ("flashcards", "flashcard")):
        rows = await pg_client.execute_query(
            f"SELECT concept_id FROM {table} WHERE id::text = :id AND user_id = :uid LIMIT 1",
            {"id": item_id, "uid": user_id},
        )
        if rows and rows[0].get("concept_id"):
            return str(rows[0]["concept_id"]), how

    if neo4j_client is not None:
        found = await neo4j_client.execute_query(
            "MATCH (c:Concept {id: $id, user_id: $uid}) RETURN c.id AS id LIMIT 1",
            {"id": item_id, "uid": user_id},
        )
        if found:
            return item_id, "concept"

    raise UnresolvableReviewTarget(
        f"feed item {item_id!r} is not a quiz, flashcard or concept of this user; send concept_id"
    )
