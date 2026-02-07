
import asyncio
import json
from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client

async def check_db():
    print("--- PostgreSQL Duplicates ---")
    pg = await get_postgres_client()
    
    # Check notes duplicates
    notes = await pg.execute_query("SELECT content_hash, count(*) FROM notes WHERE content_hash IS NOT NULL GROUP BY content_hash HAVING count(*) > 1")
    print(f"Duplicate Notes (by hash): {len(notes)}")
    for n in notes:
        print(f"  Hash: {n['content_hash'][:10]}... Count: {n['count']}")

    # Check quizzes duplicates
    quizzes = await pg.execute_query("SELECT question_text, concept_id, count(*) FROM quizzes GROUP BY question_text, concept_id HAVING count(*) > 1")
    print(f"Duplicate Quizzes: {len(quizzes)}")
    
    # Check concept duplicates in Neo4j
    print("\n--- Neo4j Duplicates ---")
    neo = await get_neo4j_client()
    concepts = await neo.execute_query("MATCH (c:Concept) WITH c.name AS name, c.user_id AS user_id, count(*) AS count WHERE count > 1 RETURN name, user_id, count")
    print(f"Duplicate Concepts: {len(concepts)}")
    for c in concepts:
        print(f"  Name: {c['name']} (User: {c['user_id']}) Count: {c['count']}")

if __name__ == "__main__":
    asyncio.run(check_db())
