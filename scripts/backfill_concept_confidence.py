"""Backfill confidence scores for existing Concept nodes that lack them.

Usage:
    python -m scripts.backfill_concept_confidence
"""

import asyncio

from backend.db.neo4j_client import get_neo4j_client


async def backfill_confidence(default_confidence: float = 0.8) -> None:
    neo = await get_neo4j_client()
    # Use execute_write to ensure this runs in a write transaction
    result = await neo.execute_write(
        """
        MATCH (c:Concept)
        WHERE c.confidence IS NULL
        SET c.confidence = $default_confidence
        RETURN count(c) AS updated
        """,
        {"default_confidence": default_confidence},
    )
    updated = result[0]["updated"] if result else 0
    print(f"Updated {updated} Concept nodes with confidence={default_confidence}.")

    # Also backfill relationship strength and mention_count
    rel_result = await neo.execute_write(
        """
        MATCH ()-[r]->()
        WHERE r.strength IS NULL
        SET r.strength = 1.0, r.mention_count = coalesce(r.mention_count, 1)
        RETURN count(r) AS updated
        """,
    )
    rel_updated = rel_result[0]["updated"] if rel_result else 0
    print(f"Updated {rel_updated} relationships with default strength=1.0.")


if __name__ == "__main__":
    asyncio.run(backfill_confidence())
