import asyncio
import os
from dotenv import load_dotenv
from backend.graphs.chat_graph import run_chat

load_dotenv()

async def test_chat():
    print("--- Testing Chat Graph Flow ---")
    user_id = "test_user_001"
    message = "What is Spaced Repetition?"
    
    print(f"Input: {message}")
    
    try:
        response = await run_chat(
            user_id=user_id,
            message=message
        )
        
        print("\n✅ Chat Response:")
        print(response.get("response", "No response text found"))
        print("\nRelated Concepts:")
        print(response.get("related_concepts", []))
        
    except Exception as e:
        print(f"\n❌ Chat Graph Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_chat())
