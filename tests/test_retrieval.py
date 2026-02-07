import asyncio
import os
from dotenv import load_dotenv

# Load env before imports if needed
load_dotenv()

from backend.services.retrieval_service import RetrievalService
from backend.db.postgres_client import close_postgres_client

async def test_retrieval():
    service = RetrievalService()
    
    query = "chunking strategy"
    print(f"Testing retrieval for query: '{query}'")
    
    try:
        results = await service.search(query=query, user_id="test_user", limit=3)
        
        print(f"\nFound {len(results)} results:")
        for r in results:
            print(f"- [Score: {r['similarity']:.4f}] {r['child_content'][:100]}...")
            print(f"  Parent Context: {r['parent_content'][:50]}...")
            
    except Exception as e:
        print(f"Retrieval failed: {e}")
    finally:
        await close_postgres_client()

if __name__ == "__main__":
    asyncio.run(test_retrieval())
