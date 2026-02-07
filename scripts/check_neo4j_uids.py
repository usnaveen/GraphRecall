
import asyncio
from backend.db.neo4j_client import get_neo4j_client
import os

async def check_user_ids():
    NEO4J_URI = os.getenv("NEO4J_URI")
    NEO4J_USER = os.getenv("NEO4J_USER")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
    
    neo = await get_neo4j_client()
    res = await neo.execute_query("MATCH (c:Concept) RETURN c.user_id as uid LIMIT 5")
    print("User IDs found in Neo4j:")
    for r in res:
        print(f" - {r['uid']}")

if __name__ == "__main__":
    asyncio.run(check_user_ids())
