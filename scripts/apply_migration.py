import asyncio
import os
from dotenv import load_dotenv
from backend.db.postgres_client import PostgresClient, PostgresSettings

load_dotenv()

async def run_migration():
    # Hardcode URL as fallback
    db_url = os.getenv("DATABASE_URL")
    if not db_url or "localhost" in db_url:
        print("DATABASE_URL missing or localhost, using Supabase...")
        db_url = "postgresql://postgres.gkhhecrbbyrautfuruuh:rAzD6ityq2Di9XSJ@aws-1-ap-south-1.pooler.supabase.com:6543/postgres"
    
    print(f"Connecting to: {db_url.split('@')[-1]}")
    
    # Explicitly pass settings
    settings = PostgresSettings(database_url=db_url)
    client = PostgresClient(settings=settings)
    await client.initialize()
    
    try:
        with open("backend/db/migrations/011_add_is_liked.sql", "r") as f:
            sql = f.read()
            
        print("Running migration 011_add_is_liked.sql...")
        # Split by ; manually because client.execute_update executes single statement usually
        # But wait, postgres_client._split_sql_statements is static. I can use it.
        statements = client._split_sql_statements(sql)
        for stmt in statements:
            await client.execute_update(stmt)
        print("Migration successful.")
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
