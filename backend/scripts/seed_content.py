
import asyncio
import os
import sys

# Add directory to path so we can import backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'backend', '.env')
load_dotenv(env_path)
print(f"Loading env from {env_path}")

from backend.graphs.ingestion_graph import run_ingestion
from backend.services.feed_service import FeedService
from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client

async def seed_content(file_path: str):
    target_email = "usnaveen25@gmail.com"
    log_file = "backend/scripts/seed_result.txt"
    
    def log(msg):
        print(msg)
        with open(log_file, "a") as f:
            f.write(msg + "\n")
            
    # Clear log
    with open(log_file, "w") as f:
        f.write(f"Starting seed for {target_email}\n")

    log(f"🌱 Seeding content from {file_path} for {target_email}...")
    
    try:
        pg_client = await get_postgres_client()
        
        # 0. Find Target User
        log(f"\n👤 Looking up user {target_email}...")
        users = await pg_client.execute_query(
            "SELECT id FROM users WHERE email = :email",
            {"email": target_email}
        )
        
        if not users:
            log(f"❌ User {target_email} not found! Please log in to the app first.")
            return

        user_id = users[0]["id"]
        log(f"   - Found User ID: {user_id}")

        with open(file_path, "r") as f:
            content = f.read()
            
        if not content:
            log("❌ File is empty!")
            return

        log(f"📦 Content length: {len(content)} chars")
        
        # 1. Run Ingestion
        log("\n🚀 Starting Ingestion Workflow...")
        # skip_review=True to auto-approve
        result = await run_ingestion(
            content=content,
            title="Deep Learning Fundamentals",
            user_id=user_id,
            skip_review=True 
        )
        
        if result.get("status") == "error":
            log(f"❌ Ingestion Failed: {result.get('error')}")
            return
            
        log("✅ Ingestion Complete!")
        log(f"   - Note ID: {result.get('note_id')}")
        log(f"   - Concepts Created: {len(result.get('concept_ids', []))}")
        log(f"   - Flashcards Created: {len(result.get('flashcard_ids', []))}")
        
        # 2. Trigger Feed Generation
        log("\n🔄 generating Feed and Stats...")
        neo4j_client = await get_neo4j_client()
        feed_service = FeedService(pg_client, neo4j_client)
        
        # Force generate feed for this user
        feed = await feed_service.get_feed_items(user_id, max_items=10)
        log(f"✅ Feed Generated: {len(feed)} items ready.")
        
        log("\n🎉 Seeding Finished Successfully!")
        
    except Exception as e:
        log(f"❌ Error during seeding: {e}")
        import traceback
        with open(log_file, "a") as f:
            traceback.print_exc(file=f)
            
        if not content:
            print("❌ File is empty!")
            return

        print(f"📦 Content length: {len(content)} chars")
        
        # 1. Run Ingestion
        print("\n🚀 Starting Ingestion Workflow...")
        # skip_review=True to auto-approve and make it fast
        result = await run_ingestion(
            content=content,
            title="Deep Learning Fundamentals",
            user_id=user_id,
            skip_review=True 
        )
        
        if result.get("status") == "error":
            print(f"❌ Ingestion Failed: {result.get('error')}")
            return
            
        print("✅ Ingestion Complete!")
        print(f"   - Note ID: {result.get('note_id')}")
        print(f"   - Concepts Created: {len(result.get('concept_ids', []))}")
        print(f"   - Flashcards Created: {len(result.get('flashcard_ids', []))}")
        
        # 2. Trigger Feed Generation
        print("\n🔄 generating Feed and Stats...")
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        feed_service = FeedService(pg_client, neo4j_client)
        
        # Force generate feed for this user
        feed = await feed_service.get_feed_items(user_id, max_items=10)
        print(f"✅ Feed Generated: {len(feed)} items ready.")
        
        print("\n🎉 Seeding Finished Successfully! Restart the app or refresh to see data.")
        
    except Exception as e:
        print(f"❌ Error during seeding: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="Path to markdown file")
    args = parser.parse_args()
    
    asyncio.run(seed_content(args.file))
