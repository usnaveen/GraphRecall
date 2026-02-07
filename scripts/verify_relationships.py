
import asyncio
import os
from backend.db.neo4j_client import get_neo4j_client, Neo4jClient

async def check_relationships():
    print("🚀 Checking Neo4j Relationships...")
    
    # Needs valid env vars!
    if not os.getenv("NEO4J_URI"):
        print("❌ NEO4J_URI not set")
        return

    client = await get_neo4j_client()
    
    # 1. Count Concepts
    print("\n📊 Concept Counts:")
    counts = await client.execute_query("MATCH (c:Concept) RETURN count(c) as count")
    print(f"Total Concepts: {counts[0]['count']}")
    
    # 2. Count Relationships
    print("\n🔗 Relationship Counts:")
    rels = await client.execute_query("MATCH ()-[r]->() RETURN type(r) as type, count(r) as count")
    for row in rels:
        print(f" - {row['type']}: {row['count']}")
        
    if not rels:
        print("⚠️ NO RELATIONSHIPS FOUND!")
        
    # 3. Check for specific user (if we can identify one)
    # Let's list usage by user_id
    print("\n👤 Concepts by User:")
    users = await client.execute_query("MATCH (c:Concept) RETURN c.user_id as user, count(c) as count")
    for row in users:
        print(f" - {row['user']}: {row['count']}")
        
    # 4. Check connectivity sample
    print("\n🕸️ Connectivity Sample (First 5 relationships):")
    sample = await client.execute_query("""
        MATCH (a:Concept)-[r]->(b:Concept) 
        RETURN a.name, type(r), b.name LIMIT 5
    """)
    for row in sample:
        print(f"   {row['a.name']} --[{row['type(r)']}]--> {row['b.name']}")

    await client.close()

if __name__ == "__main__":
    asyncio.run(check_relationships())
