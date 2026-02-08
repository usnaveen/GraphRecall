import asyncio

from backend.db.neo4j_client import get_neo4j_client


async def backfill_confidence(default_confidence: float = 0.8) -> None:
    neo = await get_neo4j_client()
    result = await neo.execute_query(
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


if __name__ == "__main__":
    asyncio.run(backfill_confidence())
