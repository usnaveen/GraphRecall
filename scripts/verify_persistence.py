import asyncio
import os
import sys
import uuid
from datetime import datetime
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.graphs.ingestion_graph import run_ingestion
from backend.services.feed_service import FeedService
from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client
from backend.models.feed_schemas import FeedItemType

async def verify_persistence():
    print("🚀 Starting Persistence Verification...")
    
    pg_client = await get_postgres_client()
    neo4j_client = await get_neo4j_client()
    feed_service = FeedService(pg_client, neo4j_client)
    
    # 1. Ingest a unique test note
    note_content = f"Python is a diverse language. It supports OOP and functional programming. Persistence is key for databases. Unique Run ID: {uuid.uuid4()}"
    print(f"\n📝 Ingesting Note: {note_content[:50]}...")
    
    result = await run_ingestion(
        content=note_content,
        title="Persistence Test Note",
        user_id="test_user_persistence",
        skip_review=True # Auto-approve to trigger generation
    )
    
    if result["status"] == "error":
        print(f"❌ Ingestion Failed: {result.get('error')}")
        return

    concept_ids = result.get("concept_ids", [])
    quiz_ids = result.get("quiz_ids", [])
    
    print(f"✅ Ingestion Complete.")
    print(f"   Note ID: {result.get('note_id')}")
    print(f"   Created Concepts: {len(concept_ids)}")
    print(f"   Generated Quizzes (in graph result): {len(quiz_ids)}")
    
    if not quiz_ids:
        print("⚠️ No quizzes returned in result. Checking DB directly might be needed or generation skipped.")
    
    # 2. Check DB for Quizzes
    print("\n🔍 Checking 'quizzes' table...")
    quizzes = await pg_client.execute_query(
        "SELECT id, question_text FROM quizzes WHERE user_id = 'test_user_persistence' ORDER BY created_at DESC LIMIT 5"
    )
    
    if quizzes:
        print(f"✅ Found {len(quizzes)} quizzes in DB:")
        for q in quizzes:
            print(f"   - {q['question_text'][:50]}... (ID: {q['id']})")
    else:
        print("❌ No quizzes found in DB for test user!")
    
    # 3. Verify FeedService uses DB content
    print("\n🧪 Testing FeedService (should use DB content)...")
    
    if concept_ids:
        # Get a concept definition to pass to generate_feed_item
        # We need the full concept dict as expected by feed_service
        # For simplicity, we'll fetch it from Neo4j or just mock it if we have ID
        concept_id = concept_ids[0]
        
        # Fetch from Neo4j to get name/domain for the dict
        concept_data = await neo4j_client.execute_query(
            "MATCH (c:Concept {id: $id}) RETURN c.name as name, c.domain as domain, c.definition as definition",
            {"id": concept_id}
        )
        
        if concept_data:
            c_row = concept_data[0]
            concept_dict = {
                "id": concept_id,
                "name": c_row["name"],
                "definition": c_row["definition"],
                "domain": c_row["domain"],
                "complexity_score": 5,
                "priority_score": 1.0
            }
            
            print(f"   Requesting MCQ for concept: {c_row['name']} (ID: {concept_id})")
            
            # Call generate_feed_item
            feed_item = await feed_service.generate_feed_item(
                concept=concept_dict,
                item_type=FeedItemType.MCQ,
                user_id="test_user_persistence"
            )
            
            if feed_item and feed_item.content:
                 q_text = feed_item.content.get("question", "")
                 print(f"   Feed Item Returned: {q_text[:50]}...")
                 
                 # Check if this question text exists in the DB rows we fetched
                 is_persisted = any(q['question_text'] == q_text for q in quizzes)
                 if is_persisted:
                     print("✅ SUCCESS: FeedService returned a quiz that exists in DB!")
                 else:
                     print("⚠️ WARNING: FeedService returned a quiz NOT found in common DB list (could be new generation or pagination issue).")
            else:
                 print("❌ FeedService returned None.")
        else:
             print("❌ Could not fetch concept details from Neo4j.")
    else:
        print("⚠️ No concepts created, skipping FeedService test.")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(verify_persistence())
