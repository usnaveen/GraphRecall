import asyncio
import os
import sys

# Add project root to path so we can import backend
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client

async def reset_content_data():
    """
    Wipes all Content (Notes, Chunks, Concepts, Propositions) 
    but KEEPS Users and Auth data safe.
    """
    print("⚠️  STARTING DATA RESET (Keeping Users) ⚠️")
    
    # 1. Postgres Cleanup
    pg = await get_postgres_client()
    try:
        # Delete independent tables first to avoid FK constraints matches? 
        # Actually cascade should handle it from Notes.
        
        print("Cleaning PostgreSQL...")
        # Order matters!
        await pg.execute_update("TRUNCATE TABLE feed_items CASCADE;")
        await pg.execute_update("TRUNCATE TABLE flashcards CASCADE;")
        await pg.execute_update("TRUNCATE TABLE quizzes CASCADE;")
        await pg.execute_update("TRUNCATE TABLE propositions CASCADE;")
        await pg.execute_update("TRUNCATE TABLE chunks CASCADE;")
        await pg.execute_update("TRUNCATE TABLE notes CASCADE;")
        print("✅ Postgres Content Cleared.")
        
    except Exception as e:
        print(f"❌ Postgres Error: {e}")

    # 2. Neo4j Cleanup
    neo = await get_neo4j_client()
    try:
        print("Cleaning Neo4j...")
        # Detach delete all nodes EXCEPT Users (if you verify users there? We usually don't sync users to Neo4j yet?)
        # Actually we do have User nodes maybe?
        # Safe bet: Delete Concepts, Chunks, Propositions, NoteSource
        
        query = """
        MATCH (n)
        WHERE n:Concept OR n:Chunk OR n:Proposition OR n:NoteSource OR n:LearningItem
        DETACH DELETE n
        """
        await neo.execute_query(query)
        print("✅ Neo4j Content Cleared.")
        
    except Exception as e:
        print(f"❌ Neo4j Error: {e}")

    print("\n✨ SYSTEM RESET COMPLETE. READY FOR FRESH INGESTION. ✨")

if __name__ == "__main__":
    import dotenv
    dotenv.load_dotenv()
    asyncio.run(reset_content_data())
