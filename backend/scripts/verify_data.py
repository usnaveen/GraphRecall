
import asyncio
import os
import sys
from dotenv import load_dotenv

# Add directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Load env
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'backend', '.env')
load_dotenv(env_path)

from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client

async def verify(user_id: str = "0d9a7637-9870-4363-a3f7-0e1b2fc72a44"):
    print(f"🔍 Verifying data for User ID: {user_id}")
    
    try:
        # Check Postgres Users
        pg = await get_postgres_client()
        users = await pg.execute_query("SELECT * FROM users LIMIT 5")
        print(f"\n👤 Users Found: {len(users)}", flush=True)
        for u in users:
            print(f"   - {u['email']} (ID: {u['id']})", flush=True)

        # Check Postgres Notes
        pg = await get_postgres_client()
        notes = await pg.execute_query(
            "SELECT id, title, user_id, created_at FROM notes LIMIT 10"
        )
        print(f"\n📝 Total Notes Found (Any User): {len(notes)}", flush=True)
        for n in notes:
            print(f"   - {n['title']} (User: {n['user_id']})", flush=True)
            
        # Check Neo4j Concepts
        neo = await get_neo4j_client()
        concepts = await neo.execute_query(
            "MATCH (c:Concept {user_id: $uid}) RETURN c.name, c.id",
            {"uid": user_id}
        )
        print(f"\n🧠 Concepts Found: {len(concepts)}")
        for c in concepts[:5]:
             print(f"   - {c['c.name']}")
        if len(concepts) > 5:
            print(f"   ... and {len(concepts)-5} more")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--user_id", default="0d9a7637-9870-4363-a3f7-0e1b2fc72a44", help="User ID to verify")
    args = parser.parse_args()
    
    asyncio.run(verify(args.user_id))
