
import asyncio
from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client
from backend.services.feed_service import FeedService
from backend.models.feed_schemas import FeedFilterRequest

async def verify_feed():
    print("--- Verifying Feed Logic ---")
    pg = await get_postgres_client()
    neo = await get_neo4j_client()
    
    # Check if we have any concepts
    concepts = await neo.execute_query("MATCH (c:Concept) RETURN count(c) as count")
    print(f"Total Concepts in Neo4j: {concepts[0]['count']}")
    
    if concepts[0]['count'] == 0:
        print("WAINING: No concepts in Neo4j. Feed will be empty unless Web Search works.")
    
    # Run FeedService.get_feed for test user
    fs = FeedService(pg, neo)
    req = FeedFilterRequest(
        user_id="00000000-0000-0000-0000-000000000001",
        max_items=10
    )
    
    try:
        res = await fs.get_feed(req)
        print(f"Feed Items: {len(res.items)}")
        for i, item in enumerate(res.items):
            print(f"  {i+1}. Type: {item.item_type}, Concept: {item.concept_name}")
    except Exception as e:
        print(f"ERROR: FeedService.get_feed failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(verify_feed())
