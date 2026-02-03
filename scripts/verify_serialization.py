import json
from datetime import datetime, timezone
from backend.models.feed_schemas import FeedResponse, FeedItem, FeedItemType

def test_serialization():
    print("🚀 Testing Feed Response Serialization...")
    
    # Create mock items
    items = [
        FeedItem(
            id="test-id-1",
            item_type=FeedItemType.MCQ,
            content={
                "question": "What is 2+2?",
                "options": [{"id": "opt1", "text": "4", "is_correct": True}],
                "explanation": "Math",
                "concept_name": "Addition"
            },
            concept_id="concept-123",
            concept_name="Addition",
            domain="Math"
        ),
        FeedItem(
            id="test-id-2",
            item_type=FeedItemType.CONCEPT_SHOWCASE,
            content={
                "concept_name": "Showcase",
                "definition": "Def",
                "domain": "General"
            }
        )
    ]
    
    response = FeedResponse(
        items=items,
        total_due_today=5,
        completed_today=0,
        streak_days=1
    )
    
    # Simulate FastAPI serialization (model_dump_json)
    json_output = response.model_dump_json()
    parsed = json.loads(json_output)
    
    print("\n✅ Serialized Output:")
    print(json.dumps(parsed, indent=2))
    
    # Verify strict equality
    first_item = parsed["items"][0]
    print(f"\n🕵️ Checking Item 1 Type: {first_item['item_type']} (Expected 'mcq')")
    
    if first_item['item_type'] != 'mcq':
        print("❌ FORMAT MISMATCH! Enum not serialized to value.")
    else:
        print("✅ Item Type serialized correctly.")

if __name__ == "__main__":
    test_serialization()
