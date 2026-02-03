import asyncio
import os
import sys
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.db.postgres_client import get_postgres_client

async def reset_data_keep_latest():
    print("🚀 Starting Data Reset (Keeping Latest Note)...")
    
    pg_client = await get_postgres_client()
    
    # 1. Find the latest note ID globally (or per user if we had user context, but assuming global/dev single user for now)
    # Get latest created note
    result = await pg_client.execute_query(
        "SELECT id, title, created_at FROM notes ORDER BY created_at DESC LIMIT 1"
    )
    
    latest_note_id = None
    if result:
        latest_note_id = str(result[0]["id"])
        print(f"✅ Found latest note: {result[0]['title']} (ID: {latest_note_id})")
    else:
        print("⚠️ No notes found. Wiping everything.")

    # 2. Delete everything EXCEPT related to this note
    # Strategy: 
    # - Delete all notes WHERE id != latest_note_id
    # - Delete all quizzes, flashcards, proficiency_scores, study_sessions (cascade should handle some, but let's be explicit)
    # Actually, simpler: Delete ALL quizzes/flashcards/chat to reset "state", and delete old notes.
    # The user said "dump everything in the database except the last note". 
    # This implies we want to clear the "generated" stuff too so it regenerates properly with new code.
    
    print("\n🗑️ Deleting old notes...")
    if latest_note_id:
        await pg_client.execute_update(
            "DELETE FROM notes WHERE id != :id",
            {"id": latest_note_id}
        )
    else:
        await pg_client.execute_update("DELETE FROM notes")
        
    # Wipe generated content to force regeneration with new "Source" logic/Columns
    print("🗑️ Wiping generated content (quizzes, flashcards, chats)...")
    await pg_client.execute_update("DELETE FROM quizzes")
    await pg_client.execute_update("DELETE FROM flashcards")
    await pg_client.execute_update("DELETE FROM chat_messages")
    await pg_client.execute_update("DELETE FROM chat_conversations")
    await pg_client.execute_update("DELETE FROM study_sessions")
    # We might want to keep proficiency scores if they are linked to the concept of the remaining note...
    # But usually a "dump" implies a fresh start. Let's wipe scores too.
    await pg_client.execute_update("DELETE FROM proficiency_scores")

    print("\n✨ Data reset complete. Latest note preserved (if it existed).")
    
if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(reset_data_keep_latest())
