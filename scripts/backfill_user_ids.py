
import asyncio
from backend.db.neo4j_client import get_neo4j_client
import os

async def backfill_user_ids():
    NEO4J_URI = os.getenv("NEO4J_URI")
    NEO4J_USER = os.getenv("NEO4J_USER")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
    
    test_user_id = "00000000-0000-0000-0000-000000000001"
    
    neo = await get_neo4j_client()
    print(f"Backfilling all concepts with user_id: {test_user_id}")
    
    query = """
    MATCH (c:Concept)
    WHERE c.user_id IS NULL
    SET c.user_id = $uid
    RETURN count(c) as count
    """
    res = await neo.execute_query(query, {"uid": test_user_id})
    print(f"Updated {res[0]['count']} concept nodes.")

if __name__ == "__main__":
    asyncio.run(backfill_user_ids())
