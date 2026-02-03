import asyncio
import os
import json
import logging
from backend.main import app
from backend.models.feed_schemas import FeedResponse
from httpx import AsyncClient, ASGITransport

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def debug_feed():
    print("🚀 Debugging Feed Response...")
    
    # Needs a valid user in DB. We can mock it or use a test user if we knew the ID.
    # Since we can't easily login via Google OAuth flow in script without a token,
    # we will bypass auth by mocking `get_current_user` dependency or just using a generated token if possible.
    # EASIER: We can just use the Service directly to see what it generates!
    
    # But checking the API endpoint is better to see serialization.
    # Let's override the dependency.
    
    from backend.auth.middleware import get_current_user
    
    mock_user = {
        "id": "test_user_DEBUG_FEED",
        "email": "test@example.com",
        "name": "Test User",
        "google_id": "test_google_id"
    }
    
    app.dependency_overrides[get_current_user] = lambda: mock_user
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        print("📥 Fetching /api/feed...")
        response = await ac.get("/api/feed")
        
        if response.status_code != 200:
            print(f"❌ Error: {response.status_code}")
            print(response.text)
            return

        data = response.json()
        print(f"✅ Success! Received {len(data.get('items', []))} items.")
        
        # Print first item structure
        if data.get('items'):
            first_item = data['items'][0]
            print("\n🔍 First Item Structure:")
            print(json.dumps(first_item, indent=2))
            
            # Check for critical fields expected by Frontend
            print("\n🕵️ Checking Frontend compatibility:")
            print(f" - id: {first_item.get('id')}")
            print(f" - item_type: {first_item.get('item_type')}")
            print(f" - content: {type(first_item.get('content'))}")
            
            if first_item.get('item_type') == 'mcq':
                print(" - [MCQ] content.options check:")
                opts = first_item['content'].get('options', [])
                if opts:
                    print(f"   First option keys: {opts[0].keys()}")
        else:
            print("⚠️ Response contained NO items.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(debug_feed())
